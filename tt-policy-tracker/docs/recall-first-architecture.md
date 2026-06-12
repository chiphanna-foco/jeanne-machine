# Recall-First Architecture

_The step-back (2026-06-11): why the pipeline kept missing laws, and the redesign._

## The goal, stated plainly

Surface every law that affects TurboTenant's landlords (small, self-managing,
1–5 properties) and TurboTenant's product surfaces — screening, applications,
leases, rent payments, deposits, notices/evictions, listings, insurance — to
the legal team, reliably enough that company policy and product behavior can
track the law.

That makes this a **legal-compliance feed**, and it fixes the error economics:

| | Cost |
|---|---|
| **False negative** (missed law) | Compliance exposure for thousands of landlords. Silent. |
| **False positive** (noise item) | One reviewer click (👎) to dismiss. Visible. |

So the system must be **recall-first at ingest and classification**, with
precision managed at the human layer (triage buckets + 👍/👎 feedback).

## What was wrong before

The original pipeline was a chain of lossy filters, each tuned to save LLM
cost: keyword prescreen → thin masterlist summaries → a deliberately STRICT
classifier prompt → a 0.6 confidence cutoff → enrichment batch caps. Every
stage could silently drop a law, and the cost being protected was trivial
(~2,000 housing-candidate bills/year nationally ≈ single-digit dollars of
Haiku). CO HB26-1196 — a **signed** tenant-screening law squarely inside
TurboTenant's product — was dropped by quota starvation, then by a source gap,
then by boilerplate summaries, then by classifier strictness. Each fix
revealed the next leak because the architecture itself filtered on the
weakest possible signal.

The decisive measurement: one LegiScan national full-text query for
"tenant screening" returns HB26-1196 as the **#2 most relevant bill in the
country (relevance 99/100)**. Discovery was never hard — we were just doing it
on the wrong input.

## The design

```
DISCOVERY   adapters/legiscan_search.py
            ~16 standing queries (TurboTenant product surfaces) ×
            getSearchRaw state=ALL → LegiScan's full-text index over actual
            bill text, national. change_hash makes re-runs incremental.

ANALYSIS    getBill for new/changed matches (subjects, history, official link)
            → recall-first classifier that knows TurboTenant, the 1-5 unit
            segment, and WHY the bill matched ("Matched policy searches: ...")
            → Sonnet summary with a small-landlord lens (applicability
            thresholds called out — many laws exempt small/owner-occupied).

PRECISION   the human layer: triage buckets (act_now/monitor/fyi),
            cross-source dedup, 👍/👎/👀 feedback with suppression and a
            precision metric. Noise costs one click and never returns.

ALERTING    enrichment/alerting.py — recall-first INGEST, act-now ALERTS.
            Slack pings only what binds landlords within ~3-6 months (urgent
            label or effective date in [today-90d, today+180d]); speculative
            bills with 6+ months of runway are tracked silently. Compact
            one-line format, capped per run (SLACK_MAX_ALERT_ITEMS, default 8)
            so a 50-state backfill drains over runs instead of blasting.
            /admin/cron-search runs the search sweep every 2 hours
            (.github/workflows/cron-search.yml) — LegiScan's search cache
            refreshes hourly, so 2h is "as often as useful"; a quiet run
            costs ~16 queries; the endpoint self-skips if a run is active.
```

Key recall properties:
- Discovery searches **full bill text**, so vaguely-titled bills match on
  their substance. `since` windows are deliberately not used for search
  discovery — an old-but-never-ingested law should still surface;
  `change_hash` is the incremental mechanism.
- The classifier treats curated metadata (`Subjects:` tags, matched search
  terms) as strong relevance evidence and is instructed that thin boilerplate
  summaries are **not** evidence of irrelevance.
- "Found by search but rejected by classifier" is now a loggable, auditable
  set — recall failures stop being silent.
- Caps are never silent: getBill overflow beyond the per-run cap is logged
  and self-heals next run (unseen change_hash).

## Source roles after this change

| Source | Role |
|---|---|
| LegiScan **search** (`legiscan_search`) | **Primary** state-bill discovery, national |
| LegiScan masterlist (`legiscan`) | Targeted `?state=` backfills (gap states) |
| Open States | Rotation sweep retained as cross-check; candidate for retirement |
| wa_leg | First-party WA (richer/earlier data) |
| congress / federal_register | Federal |
| courtlistener / legistar / bls_cpi | Courts / local / CPI rent-cap math |

## Quota math (LegiScan free tier: 30k/mo)

Daily sweep: 16 `getSearchRaw` + `getBill` only for new/changed matches.
Steady state after the first backfill run is dominated by genuinely-changed
bills (~tens/day) → roughly 1–3k queries/month. Comfortable.

## What this supersedes

`docs/coverage-gap-plan.md` Phases 2–3 (per-state gap audit + masterlist-raw
work loop): national search discovery covers every state at once, so the
per-state gap-hunting machinery is no longer the primary path. The plan's
house-rules section (hashes, timing, CC BY 4.0 attribution) still applies.

## Still open

- Web UI attribution credit: "Data via LegiScan (CC BY 4.0)".
- Feedback → classifier learning loop (few-shot from 👍/👎) once votes
  accumulate; "ask a question" per item via getBillText.
- Retire the Open States rotation once search-vs-OS overlap data confirms
  search dominance.
- Teach `audit.py` trace/coverage about LegiScan external_ids.
