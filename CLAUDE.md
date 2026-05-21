# CLAUDE.md — operating rules for Claude Code sessions on this repo

## Minimize terminal usage by the human

The user is busy and shouldn't have to hand-curl admin endpoints in a loop. Build for one-curl-and-walk-away from the start.

**Always prefer these patterns:**

1. **Loop inside the endpoint, not inside the user's terminal.** If an operation might need N retries / N batches / N polls, build an admin endpoint that does the loop itself in a background task and pushes a Slack notification when done. Bad: "now run this curl 12 times." Good: `/admin/drain-X` that runs all 12 batches internally.

2. **Push completion to Slack, don't make the user poll.** When a long-running admin task finishes (`drain-enrich`, `run-pipeline`, any backfill), send a Slack message via `digest/slack.py:send_to_slack` summarizing the result. Settings already has `slack_webhook_url`. The user gets pinged instead of refreshing `pipeline-status` every 5 minutes.

3. **Combine related operations.** When the human will obviously want both (e.g. "ingest WA bills" then "enrich them"), build a single endpoint that does both in sequence. Don't make them curl twice.

4. **Surface live progress in `_pipeline_status`.** Long-running background tasks should write incremental progress to `_pipeline_status["last_result"]` between sub-steps, not only at the end. That way *if* the user does poll, they see live counts.

5. **Default verbose, opt out for terse.** Status endpoints should return per-state / per-source breakdowns by default. Don't make the user run three different curls to assemble a picture.

## Sandbox limits Claude has to work around

- **No outbound HTTP to Railway.** `jeanne-machine.up.railway.app` is not in the curl allowlist for the Claude sandbox. Claude **cannot** invoke admin endpoints itself — only the user can. Build endpoints that need zero follow-up, not endpoints that need Claude to babysit them.
- **No Docker daemon, no local DB, no real API keys.** Everything is verified by the user against prod via the admin endpoints. Plan accordingly — instrument endpoints so they return enough JSON for diagnosis in one call.
- **WebFetch 403s most external sites.** When third-party APIs need probing, build an admin endpoint that probes them from Railway (which IS allowed outbound). Don't ask the user to relay browser requests.

## Git flow

- Develop on `claude/add-legislature-bill-tracking-Uq9t2` (current branch). 
- After each meaningful change: commit, push (force-with-lease if needed), open a PR to `main`, merge via squash.
- If `git reset --hard origin/main` is needed (to handle prior squash-merge history), **commit edits to file first** so they're not in the working tree where reset will wipe them.
- Don't worry about preserving feature-branch commit history — main is squash-merged, everything's flat.

## Architecture refresher

- FastAPI app at `tt-policy-tracker/api/main.py`, deployed on Railway, runs against Railway Postgres.
- Admin endpoints all under `/admin/*`, gated by `?token=$ADMIN_TOKEN`.
- Adapters in `tt-policy-tracker/adapters/`: `openstates`, `wa_leg` (direct WSL), `congress`, `federal_register`, `legistar`, `courtlistener`.
- Enrichment is Haiku-classifier + Sonnet-summarizer (`enrichment/classifier.py`, `enrichment/summarizer.py`).
- Backlog drainage: `/admin/drain-enrich?source=X&state=Y` loops until queue empty.
- Per-state visibility: `/admin/stats-by-state`.
- Per-bill audit: `/admin/audit/trace?bill=WA:HB1217`, `/admin/audit/coverage`.
- Diagnostics: `/admin/wsl-probe` for WSL API exploration.

## Default behaviors to maintain

- OpenStates is rate-limited to ≤9 req/min globally (`OS_MIN_REQUEST_INTERVAL = 8.0` in `adapters/openstates.py`). Don't lower this.
- `wa_leg` uses bulk-fetch + classifier filtering (WSL doesn't expose topical index). Don't try to add topic-based pre-filtering — the API doesn't support it.
- Daily cron drains 300 docs; weekly-full drains 500. If the backlog grows again, raise those, not by ingesting less.
