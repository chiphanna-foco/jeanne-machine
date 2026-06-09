# CLAUDE.md — operating rules for Claude Code sessions on this repo

## Minimize terminal usage by the human

The user is busy and shouldn't have to hand-curl admin endpoints in a loop. Build for one-curl-and-walk-away from the start.

**Always prefer these patterns:**

1. **Loop inside the endpoint, not inside the user's terminal.** If an operation might need N retries / N batches / N polls, build an admin endpoint that does the loop itself in a background task and pushes a Slack notification when done. Bad: "now run this curl 12 times." Good: `/admin/drain-X` that runs all 12 batches internally.

2. **Push completion to Slack, don't make the user poll.** When a long-running admin task finishes (`drain-enrich`, `run-pipeline`, any backfill), send a Slack message via `digest/slack.py:send_to_slack` summarizing the result. Settings already has `slack_webhook_url`. The user gets pinged instead of refreshing `pipeline-status` every 5 minutes.

3. **Combine related operations.** When the human will obviously want both (e.g. "ingest WA bills" then "enrich them"), build a single endpoint that does both in sequence. Don't make them curl twice.

4. **Surface live progress in `_pipeline_status`.** Long-running background tasks should write incremental progress to `_pipeline_status["last_result"]` between sub-steps, not only at the end. That way *if* the user does poll, they see live counts.

5. **Default verbose, opt out for terse.** Status endpoints should return per-state / per-source breakdowns by default. Don't make the user run three different curls to assemble a picture.

6. **Every new admin workflow gets a dashboard button.** When you add an `/admin/*` action, also add it to `web/app/components/AdminControls.tsx` (the ⚙️ Admin panel on jeanne-machine.vercel.app). Read-only data endpoints get a `view: true` action that renders the JSON inline. The user prefers clicking to curling — a curl-only endpoint is half-finished. `next.config.ts` already proxies `/api/*` and `/admin/*` to the backend, so no routing work is needed.

## Sandbox limits Claude has to work around

- **No *direct* outbound HTTP to Railway.** `jeanne-machine.up.railway.app` is not in the curl allowlist for the Claude sandbox, so Claude cannot `curl` admin endpoints directly. **But Claude CAN now invoke them indirectly via GitHub Actions** — see "Claude runs admin endpoints itself" below. Still prefer endpoints that need zero babysitting (loop-inside-the-endpoint, Slack-on-done), because the Actions round-trip is ~30s per call and not meant for tight polling loops.
- **No Docker daemon, no local DB, no real API keys.** Everything is verified by the user against prod via the admin endpoints. Plan accordingly — instrument endpoints so they return enough JSON for diagnosis in one call.
- **WebFetch 403s most external sites.** When third-party APIs need probing, build an admin endpoint that probes them from Railway (which IS allowed outbound). Don't ask the user to relay browser requests.

## Claude runs admin endpoints itself (GitHub Actions "remote hands")

The sandbox can't reach Railway, but GitHub Actions runners can. `.github/workflows/admin.yml` is a `workflow_dispatch` job that curls any `/admin/*` endpoint and prints the JSON response to the run log. Claude dispatches it and reads the result back — no human terminal needed.

**To call any admin endpoint:**
```bash
gh workflow run admin.yml -f path="admin/<endpoint>" -f query="<key=val&key=val WITHOUT token>"
# then find the run and read the JSON it returned:
gh run list --workflow=admin.yml -L 1                      # get the run id / status
gh run view <run-id> --log | sed -n '/response body/,/----/p'  # read the response
```
`gh run watch <run-id> --exit-status` blocks until the run finishes. The token is injected from the `ADMIN_TOKEN` repo secret — never pass it in `query`, and never print it.

**Setup:** none needed — reuses the existing `ADMIN_TOKEN` and `API_BASE_URL` repo secrets that already power the cron workflows.

**Caveats:** ~30s round-trip per call (runner spin-up) — fine for one-shot admin actions, not for tight polling. Background-task endpoints (`drain-enrich`, `run-pipeline`) return "started" immediately and still Slack their result when done, so dispatch-and-forget works exactly as before. The workflow fails the run on any HTTP ≥ 400 so errors are obvious in `gh run view`.

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
- Effective-date alerts: `/admin/cron-effective-alerts` (run daily) Slacks items taking effect within 90 days and marks `PolicyItem.effective_alert_sent_at` to dedupe. Add a Railway cron for it.

## Default behaviors to maintain

- OpenStates has TWO limits: ~10 req/min AND **250 requests/DAY** (free tier). The per-minute one is handled by `OS_MIN_REQUEST_INTERVAL = 8.0`; the per-day one is the binding constraint — a naive 50-state daily sweep blows it and every state after the cap silently 429-fails. Don't lower the 8s interval, and don't remove the per-day guards:
  - `openstates_daily_request_budget` (default 220) — class-level counter aborts before the cap.
  - Daily/weekly sweeps use `OpenStatesAdapter(rotate=True)` → only today's bucket of ~10 states is fetched (5-day cycle, 14-day overlap window), keeping each run far under 250/day. Targeted backfills (`run-pipeline?state=xx`) use `rotate=False` and fetch fully.
  - A per-day-quota 429 (body says "exceeded limit") raises `OpenStatesQuotaError` and ABORTS the sweep — never retried, because retries also count against the daily quota. Don't "fix" this by adding retries.
  - Diagnose with `/admin/os-probe?state=co&identifier=...` (shows live quota 429s + which sessions OpenStates actually has).
- `wa_leg` uses bulk-fetch + classifier filtering (WSL doesn't expose topical index). Don't try to add topic-based pre-filtering — the API doesn't support it.
- Daily cron drains 300 docs; weekly-full drains 500. If the backlog grows again, raise those, not by ingesting less.
