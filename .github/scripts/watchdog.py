#!/usr/bin/env python3
"""Watchdog for this repo's GitHub Actions crons.

Why this exists
---------------
Every cron workflow here ends with an `if: failure()` step that DMs Chip.
That step can only run once a runner has been assigned to the job, so it is
blind to the two failure modes that actually happened:

  1. Runner never acquired. On 2026-08-06 the "Twice-weekly Slack digest" run
     (31124359130) sat 15 minutes with the annotation "The job was not acquired
     by Runner of type hosted even after multiple attempts", then died with
     `runner_name: ""` and no step logs. No step ran, so no notification ran.
     The Thursday digest was simply never sent and nothing said so.
  2. The schedule never fires at all. GitHub drops and delays scheduled events
     under load (that same run was queued 1h52m after its 16:00 UTC cron). A
     dropped run produces no run record, so there is nothing to fail on.

This script is the outside observer for both. It runs in its own workflow run
-- its own runner -- so it survives whatever killed the run it is reporting on.

What it checks
--------------
  * FAILED RUNS: any run in the lookback window whose conclusion is failure /
    timed_out / startup_failure. Runs where no job ever got a runner are
    labelled as such, because that is a GitHub capacity problem and not a repo
    problem, and the two want very different responses.
  * STALE CRONS: for each workflow in STALENESS_HOURS, how long since its last
    run of any outcome. Past the threshold, the cron is presumed missed -- this
    is the only check that can catch a schedule that never fired. A cron that
    fired and failed is not "missed": the failed-run check already reported
    it, so it is not reported again as stale.

Alert state lives in a JSON file (--state) that the workflow persists through
the Actions cache, so an alert fires once rather than once per hourly sweep.
If that file is missing the script still runs, but says so in the alert: a
degraded run has to announce that it is degraded, or a repeated alert looks
like a new failure.

Exits non-zero if Slack rejects the post. A watchdog that cannot reach its
notification channel must fail loudly -- silently failing to warn is the exact
bug it was built to fix.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
SLACK_API = "https://slack.com/api/chat.postMessage"

# #chip-ai channel -- this is a side project, so its alerts go to Chip's
# personal-projects channel, not a DM. Same target as .github/actions/notify-failure
# should eventually use (it still DMs -- see that file's comment).
SLACK_CHANNEL_ID = "C0AC0C1L0NM"

# Max age of the last SUCCESSFUL run before a cron is presumed missed.
# Each is the longest legitimate gap plus roughly one period of slack, since
# GitHub routinely delays scheduled events by an hour or more.
STALENESS_HOURS = {
    "cron-daily.yml": 36,  # daily 10:00 UTC; GitHub has started it up to 9h late
    "cron-search.yml": 30,  # daily 06:15 UTC
    "cron-digest.yml": 120,  # Mon + Thu 16:00 UTC -> 4d max gap, +1d slack
    "cron-weekly-full.yml": 192,  # Fri 23:00 UTC -> 7d gap, +1d slack
}

# admin.yml and co-verify.yml are deliberately absent: both are on-demand, so
# "hasn't run lately" is their normal state. Their failures are still caught by
# the failed-run check below.

FAILING_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}

# Runs older than this are none of our business. Wider than the hourly
# schedule on purpose: if GitHub drops a sweep or two, the next one still
# sees the failure rather than skipping past it.
LOOKBACK_HOURS = 26


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def age_str(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours / 24:.1f}d"


def gh_get(path: str, token: str, **params) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "jeanne-machine-watchdog",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def runner_never_assigned(repo: str, run_id: int, token: str) -> bool:
    """True if no job in this run was ever handed to a runner.

    That is the signature of a GitHub capacity failure rather than a broken
    command: the job exists, burns its acquisition timeout, and dies with an
    empty runner_name having produced no step logs.
    """
    try:
        jobs = gh_get(f"/repos/{repo}/actions/runs/{run_id}/jobs", token).get("jobs", [])
    except urllib.error.HTTPError:
        return False
    return bool(jobs) and all(not job.get("runner_name") for job in jobs)


def collect_failed_runs(repo: str, token: str, self_run_id: str) -> list[dict]:
    cutoff = now() - timedelta(hours=LOOKBACK_HOURS)
    runs = gh_get(f"/repos/{repo}/actions/runs", token, per_page=100).get(
        "workflow_runs", []
    )

    failures = []
    for run in runs:
        if run.get("status") != "completed":
            continue
        if run.get("conclusion") not in FAILING_CONCLUSIONS:
            continue
        if parse_ts(run["created_at"]) < cutoff:
            continue
        if str(run.get("id")) == str(self_run_id):
            continue
        failures.append(
            {
                "key": f"run:{run['id']}",
                "name": run.get("name") or run.get("display_title", "?"),
                "id": run["id"],
                "url": run.get("html_url", ""),
                "conclusion": run.get("conclusion"),
                "created_at": run["created_at"],
                "no_runner": runner_never_assigned(repo, run["id"], token),
            }
        )
    return failures


def recent_runs(repo: str, workflow_file: str, token: str) -> list[dict]:
    """Newest-first runs of a workflow, read raw and filtered by us.

    Deliberately NOT `?status=success`. That filter is unreliable: on 2026-08-10 the API
    returned Aug 9 / 8 / 7 for cron-search.yml and silently omitted run 31368410789 from Aug 10,
    which is `status: completed`, `conclusion: success`, same `workflow_id`, and appears first
    when the same endpoint is called with no filter. The watchdog believed the last success was
    34h old and sent Chip a false "cron looks missed" alert. A watchdog that cries wolf gets
    muted, so it reads the raw list and decides for itself.
    """
    data = gh_get(f"/repos/{repo}/actions/workflows/{workflow_file}/runs", token, per_page=30)
    return data.get("workflow_runs", [])


def last_success(runs: list[dict]) -> dict | None:
    for run in runs:
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            return run
    return None


def last_fired(runs: list[dict]) -> dict | None:
    """Newest run that a runner actually started, whatever its outcome.

    A run that never got a runner proves the schedule fired but nothing ran;
    it is reported by the failed-run check, and it does not count here.
    """
    for run in runs:
        if run.get("conclusion") == "startup_failure":
            continue
        return run
    return None


def collect_stale_crons(repo: str, token: str) -> list[dict]:
    stale = []
    for workflow_file, max_hours in sorted(STALENESS_HOURS.items()):
        try:
            runs = recent_runs(repo, workflow_file, token)
        except urllib.error.HTTPError as exc:
            # A workflow that has been renamed or deleted should be noticed,
            # not skipped -- silence here would hide the cron disappearing.
            stale.append(
                {
                    "key": f"stale:{workflow_file}:{now():%Y-%m-%d}",
                    "workflow": workflow_file,
                    "detail": f"cannot read runs (HTTP {exc.code}) -- was it renamed or deleted?",
                }
            )
            continue

        last = last_success(runs)
        fired = last_fired(runs)
        if fired is not None and now() - parse_ts(fired["created_at"]) <= timedelta(hours=max_hours):
            # It ran recently. If that run failed, the failed-run check has
            # already said so; "looks missed" would be a second, wrong alert
            # for the same failure (Oct 2-5, 2026: every red daily run was
            # followed hours later by a "cron-daily looks missed" post).
            continue

        if last is None:
            stale.append(
                {
                    "key": f"stale:{workflow_file}:{now():%Y-%m-%d}",
                    "workflow": workflow_file,
                    "detail": "no successful run in its last 30 runs",
                }
            )
            continue

        gap = now() - parse_ts(last["created_at"])
        if gap > timedelta(hours=max_hours):
            stale.append(
                {
                    "key": f"stale:{workflow_file}:{now():%Y-%m-%d}",
                    "workflow": workflow_file,
                    "detail": (
                        f"last success {age_str(gap)} ago "
                        f"(threshold {max_hours}h) -- {last.get('html_url', '')}"
                    ),
                }
            )
    return stale


def load_state(path: str | None) -> tuple[set[str], bool]:
    """Returns (already-alerted keys, state_was_missing)."""
    if not path or not os.path.exists(path):
        return set(), True
    try:
        with open(path) as fh:
            return set(json.load(fh).get("alerted", {})), False
    except (json.JSONDecodeError, OSError):
        return set(), True


def save_state(path: str | None, keys: set[str]) -> None:
    if not path:
        return
    # Keep keys for twice the lookback so an alert cannot re-fire, but do not
    # let the file grow without bound.
    horizon = now() - timedelta(hours=LOOKBACK_HOURS * 2)
    existing, _ = load_state(path)
    stamped = {k: now().isoformat() for k in keys}
    try:
        with open(path) as fh:
            old = json.load(fh).get("alerted", {})
        for key, seen in old.items():
            if datetime.fromisoformat(seen) > horizon:
                stamped.setdefault(key, seen)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"alerted": stamped}, fh, indent=2)


def build_message(
    failures: list[dict], stale: list[dict], repo: str, state_missing: bool
) -> str:
    lines = ["🔴 *jeanne-machine cron watchdog*"]

    if failures:
        lines.append("")
        lines.append("*Failed runs*")
        for f in failures:
            when = parse_ts(f["created_at"]).strftime("%a %b %-d %H:%M UTC")
            lines.append(f"• <{f['url']}|{f['name']}> — {f['conclusion']}, {when}")
            if f["no_runner"]:
                lines.append(
                    "   ↳ no runner was ever assigned — GitHub capacity, "
                    "not repo code. The job's own failure notifier could not "
                    "fire. Re-run it."
                )

    if stale:
        lines.append("")
        lines.append("*Crons that look missed*")
        for s in stale:
            lines.append(f"• `{s['workflow']}` — {s['detail']}")

    if state_missing:
        lines.append("")
        lines.append(
            "_Alert-state cache was empty this sweep, so anything above may "
            "have already been reported once._"
        )

    lines.append("")
    lines.append(f"https://github.com/{repo}/actions")
    return "\n".join(lines)


def post_slack(token: str, text: str) -> None:
    payload = json.dumps(
        {
            "channel": SLACK_CHANNEL_ID,
            "text": text,
            "unfurl_links": False,
        }
    ).encode()
    req = urllib.request.Request(
        SLACK_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if not body.get("ok"):
        # Never print the response body -- Slack echoes request context in some
        # error payloads. The error code alone is enough to act on.
        raise SystemExit(f"::error::Slack rejected the alert: {body.get('error')}")
    print("Slack DM delivered.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--state", default=os.environ.get("WATCHDOG_STATE"))
    ap.add_argument(
        "--test-slack",
        action="store_true",
        help="Post a clearly-labelled test DM and exit, to prove delivery works.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report to stdout without posting to Slack or writing state.",
    )
    args = ap.parse_args()

    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if args.test_slack:
        if not slack_token:
            raise SystemExit("::error::SLACK_BOT_TOKEN is not set.")
        post_slack(
            slack_token,
            "🧪 *jeanne-machine watchdog — delivery test*\n"
            "This is a test post proving the watchdog can reach Chip. "
            "No cron has failed. Ignore.",
        )
        return 0

    if not args.repo:
        raise SystemExit("::error::--repo / GITHUB_REPOSITORY is required.")
    if not gh_token:
        raise SystemExit("::error::GITHUB_TOKEN is required to read run history.")

    self_run_id = os.environ.get("GITHUB_RUN_ID", "")
    seen, state_missing = load_state(args.state)

    failures = collect_failed_runs(args.repo, gh_token, self_run_id)
    stale = collect_stale_crons(args.repo, gh_token)

    new_failures = [f for f in failures if f["key"] not in seen]
    new_stale = [s for s in stale if s["key"] not in seen]

    print(
        f"scanned {args.repo}: {len(failures)} failed run(s) in the last "
        f"{LOOKBACK_HOURS}h ({len(new_failures)} new), "
        f"{len(stale)} stale cron(s) ({len(new_stale)} new), "
        f"state_missing={state_missing}"
    )
    for f in failures:
        print(f"  failed: {f['name']} #{f['id']} {f['conclusion']} no_runner={f['no_runner']}")
    for s in stale:
        print(f"  stale:  {s['workflow']} {s['detail']}")

    if not new_failures and not new_stale:
        print("Nothing new to report.")
        return 0

    message = build_message(new_failures, new_stale, args.repo, state_missing)
    print("---- alert ----")
    print(message)
    print("---------------")

    if args.dry_run:
        print("Dry run: not posting, not writing state.")
        return 0

    if not slack_token:
        raise SystemExit(
            "::error::SLACK_BOT_TOKEN is not set, so this alert cannot be "
            "delivered. Add it under Settings > Secrets and variables > Actions."
        )

    post_slack(slack_token, message)
    save_state(
        args.state,
        seen | {f["key"] for f in new_failures} | {s["key"] for s in new_stale},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
