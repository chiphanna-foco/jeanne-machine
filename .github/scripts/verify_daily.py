#!/usr/bin/env python3
"""Verify one daily pipeline run, from the "Daily pipeline" workflow.

/admin/cron-daily only starts a background task and answers "started", so a
green trigger proves nothing. This polls /admin/pipeline-status until the
record for THIS run (last_by_kind.daily, matched by run_token) is finished,
then exits 1 when the run failed in a way that would otherwise stay quiet.

The repo is public: this prints counters and doc ids only, never the status
body or the errors list (adapter error strings can carry URLs with keys).

Usage: verify_daily.py trigger.json   (env: API_BASE_URL, ADMIN_TOKEN)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

POLL_SECONDS = 60
TIMEOUT_MINUTES = 150
MAX_READ_FAILURES = 5
COUNT_KEYS = (
    "ingested", "queued", "processed", "relevant", "irrelevant",
    "api_errors", "parse_errors", "api_stop_reason", "stopped_for_time",
)


def failures(result: dict) -> list[str]:
    """Why a finished run should go red. Empty list means OK."""
    out = []
    api_errors = result.get("api_errors") or 0
    parse_errors = result.get("parse_errors") or 0
    queued = result.get("queued") or 0
    processed = result.get("processed") or 0
    ingested = result.get("ingested") or 0
    errors = len(result.get("errors") or [])
    if api_errors:
        out.append(f"{api_errors} Claude API error(s); those docs stay queued for the next run")
    if parse_errors:
        reasons = result.get("parse_failed_reasons") or {}
        ids = ", ".join(
            f"{i} ({reasons[i]})" if i in reasons else i
            for i in (result.get("parse_failed_ids") or [])
        ) or "none recorded"
        out.append(f"{parse_errors} doc(s) had unparseable model output and were dropped: {ids}")
    if queued and not processed:
        out.append(f"{queued} doc(s) were queued but none was processed")
    if errors and not ingested:
        out.append(f"{errors} ingest/pipeline error(s) and nothing was ingested")
    return out


def summary(result: dict) -> dict:
    counts = {k: result.get(k) for k in COUNT_KEYS}
    counts["errors"] = len(result.get("errors") or [])
    return counts


def find_record(status: dict, run_token: str) -> dict | None:
    rec = (status.get("last_by_kind") or {}).get("daily")
    if rec and rec.get("run_token") == run_token:
        return rec
    return None


def wait_for_run(fetch, run_token: str, sleep=time.sleep, clock=time.monotonic) -> tuple[dict | None, str]:
    """Poll until this run's record is finished. Returns (result, error)."""
    deadline = clock() + TIMEOUT_MINUTES * 60
    read_failures = 0
    while True:
        sleep(POLL_SECONDS)
        try:
            status = fetch()
        except (urllib.error.URLError, OSError, ValueError):
            read_failures += 1
            print(f"pipeline-status read failed ({read_failures} in a row)")
            if read_failures >= MAX_READ_FAILURES:
                return None, f"could not read /admin/pipeline-status {MAX_READ_FAILURES} times in a row"
            continue
        read_failures = 0
        rec = find_record(status, run_token)
        if rec is None:
            # cron-daily writes the record before it returns, so a missing
            # record means the API restarted (redeploy) and lost the run.
            return None, f"no record for daily run {run_token}; the API probably restarted mid-run"
        if not rec.get("running"):
            return rec.get("result") or {}, ""
        if clock() >= deadline:
            return None, f"daily run {run_token} still running after {TIMEOUT_MINUTES} minutes"


def main() -> int:
    with open(sys.argv[1]) as fh:
        run_token = json.load(fh).get("run_token")
    if not run_token:
        print("::error::cron-daily returned no run_token (is the deployed API older than this workflow?)")
        return 1

    url = f"{os.environ['API_BASE_URL'].rstrip('/')}/admin/pipeline-status?token={os.environ['ADMIN_TOKEN']}"

    def fetch() -> dict:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)

    result, error = wait_for_run(fetch, run_token)
    if error:
        print(f"::error::{error}")
        return 1

    counts = json.dumps(summary(result))
    print(f"daily run {run_token}: {counts}")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(f"Daily run `{run_token}`: `{counts}`\n")

    problems = failures(result)
    for p in problems:
        print(f"::error::{p}")
    if problems:
        return 1
    print("Daily run OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
