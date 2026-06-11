# State Coverage-Gap Plan

_How jeanne-machine achieves reliable 50-state bill coverage despite Open States' limits — and how we systematically find and close gaps._

## 1. The problem we hit

Colorado **HB26-1196 "Tenant Data Information"** — a squarely on-topic rental
bill (landlord PII redaction in eviction filings + tenant-screening
disclosures) — never ingested. Investigation surfaced **two independent
failure modes**:

1. **Quota starvation.** Open States' free tier caps at **250 requests/day**.
   The daily 50-state sweep exhausts the budget and aborts mid-run. On
   2026-06-10 the verify run aborted `at_state CO` with `220/220 budget
   reached` — Colorado was simply never reached.
2. **Source-coverage gap.** Even with budget and a clean `200`, Open States'
   search returns `q_search_match: false` for HB26-1196, despite carrying the
   CO 2026A session (7,348 recent items). The bill is genuinely not findable
   through their search for our query.

PR #37 made the sweep quota-aware (rotation + budget guard + abort-on-429).
That was **necessary but not sufficient**: more quota never surfaces a bill
Open States won't return. We need a *source* that carries it.

## 2. Strategy: tiered sourcing

| Tier | Source | Role | Quota |
|------|--------|------|-------|
| **0 — Backbone** | **LegiScan** | Primary multi-state index. One `getMasterList` per state returns the whole current session (title + description + last_action). | 30,000 queries/mo (~970/day) — one key, all 50 states + DC + Congress |
| **1 — First-party** | Direct adapters (`wa_leg`, future `co_leg`…) | Used where a state offers a clean first-party API and we want zero third-party dependency or richer data (full text, votes). | Per-source; WSL is effectively unlimited at our volume |
| **2 — Supplementary** | Open States | Keep for states already well-covered and as a cross-check. Now **excluded** from the states LegiScan owns, so its scarce budget stretches further. | 250/day (the constraint we're routing around) |

**Why LegiScan is the backbone, not more bespoke adapters:** building a
`wa_leg`-style adapter for all 50 states is ~50 bespoke scrapers to write and
maintain against 50 different state systems (many, like CO's Drupal site, have
no clean API at all). LegiScan normalizes all of them behind one schema and
one key, with **4× the daily quota** of Open States. Bespoke adapters become
the exception (a state with a uniquely good first-party feed), not the rule.

**Quota math.** A daily all-states refresh via LegiScan's `getMasterListRaw`
(1 call/state to read `change_hash`) + `getBill` only for changed bills is
~50–300 queries/day — comfortably inside 30,000/mo. The whole problem class
that caused the CO miss disappears.

## 3. What shipped in this PR (Phase 1 — Colorado)

- **`adapters/legiscan.py`** — `LegiScanAdapter(states=[...])`. One
  `getMasterList` call per state; normalizes every in-window bill into a
  `RawDoc`. Colorado numbers are rendered in the official `HB26-1196` form so
  search matches. Per-state `last_run_stats` mirrors the Open States breakdown.
- **Wiring** (`api/main.py`): LegiScan runs for `legiscan_states` (default
  `CO`), and those states are **removed from the Open States sweep** to avoid
  double-ingest. Targeted `?state=co` runs route through LegiScan too.
- **Config**: `LEGISCAN_API_KEY`, `LEGISCAN_STATES` (+ `.env.example`).
- **Tests**: pure normalization + window + CO-id-format tests.

### Activation (one-time, requires the operator)
1. Register a free key at <https://legiscan.com/legiscan>.
2. Set `LEGISCAN_API_KEY` in Railway (and `LEGISCAN_STATES=CO`).
3. Trigger `run-pipeline?state=co` and confirm HB26-1196 ingests
   (`api/items?state=co` → total > 0, "HB26-1196" present).

> v1 ingests `getMasterList` **summaries** (1 call/state, no `getBill` spend).
> Full bill text via `getBill` + `change_hash` diffing is Phase 3 below.

## 4. Systematic gap detection (the repeatable part)

Run this audit to find *every* under-covered state, not just CO:

1. **Build the truth set.** For each state, `getMasterListRaw?state=ST`
   (1 query) → count of bills in the current session per LegiScan.
2. **Compare to our DB.** Existing `/admin/audit/coverage?state=ST` reports
   what we actually hold. Ratio `our_count / legiscan_count` per state.
3. **Flag gaps.** Any state with a ratio well below the fleet median, or with
   a known on-topic bill missing (spot-check via `os-probe` style lookups), is
   a gap candidate.
4. **Triage the cause:**
   - _Quota_ (state never reached in the rotation) → move it to
     `LEGISCAN_STATES`.
   - _Source_ (Open States doesn't return it) → move it to `LEGISCAN_STATES`.
   - _First-party opportunity_ (state has a great API + we want full text) →
     schedule a Tier-1 direct adapter.

This audit is cheap (~50 LegiScan queries) and should run as a **monthly
scheduled job**, emitting a Slack coverage report. Silent gaps are the real
risk; this makes them loud.

## 5. Rollout phases

- **Phase 1 — Colorado (this PR).** Prove the LegiScan path end-to-end on the
  one bill we know is missing.
- **Phase 2 — Audit + onboard gap states.** Run §4 across all 50 states; add
  the worst offenders to `LEGISCAN_STATES`. Expected outcome: most of the
  ~40 states the Open States rotation can't reach daily move to LegiScan.
- **Phase 3 — getBill enrichment + change_hash (DONE for gap states, PR #40).**
  The masterlist `description` is often boilerplate (CO HB26-1196 →
  "Concerning tenant data information"), too thin for the classifier. The
  adapter now keyword-prescreens the summary and calls `getBill` only on the
  ~5% housing candidates (34 of 714 for CO), folding the `subjects` tags
  ("Housing") + action history into raw_text so the classifier has real
  signal. `change_hash` (embedded in `external_id`) skips getBill on unchanged
  bills. Next within this phase: flip LegiScan to the default all-states
  backbone via `getMasterListRaw`, demote Open States to cross-check, retire
  the rotation/budget machinery.
- **Phase 4 — Reserve bespoke adapters.** Keep `wa_leg`; add Tier-1 adapters
  only where a state's first-party feed is materially better than LegiScan
  (e.g. earlier full text, roll-call detail).

## 6. LegiScan house rules & compliance

Straight from the LegiScan API manual — the ones that shape our design:

- **30,000 queries/month, resets the 1st.** v1 spends ~1 query/state/run, so
  CO alone is ~30/mo and an all-states daily sweep ~1,500/mo — comfortably
  under. The monthly audit (§4) tracks spend.
- **Use the hashes. Really.** Phase 3's work loop is `getMasterListRaw` (or
  `getSearchRaw`) periodically → compare each bill's `change_hash` to the
  stored one → only `getBill` the changed bills, and never re-download an
  unchanged document blob. Store `change_hash` + `bill_id`.
- **`dataset_hash` is the suspension tripwire** — re-downloading an unchanged
  bulk dataset gets access suspended. We avoid the bulk `getDataset` path
  entirely (Pull API only), so this doesn't apply. If we ever adopt datasets,
  gating on `dataset_hash` is mandatory.
- **Respect timing guidelines** (manual p.7): `getMasterList`/`Raw` ~1h cache,
  `getBill` ~3h, `getSessionList` daily. Requests inside the cache window
  return cached data **and still spend a query** — so don't poll faster than
  the data can change.
- **Cache responses locally** for replayability (don't re-spend on a re-run).
- **No front-end scraping; one public key only.** We use the documented Pull
  API and a single key.
- **Attribution (CC BY 4.0).** We must credit LegiScan. We store the
  legiscan.com bill URL on every item; **TODO (web): render a "Data via
  LegiScan (CC BY 4.0)" credit** on item cards / footer.

## 7. Risks & mitigations

- **LegiScan free-tier limit (30k/mo).** `change_hash` diffing (Phase 3) keeps
  us far under it. The monthly audit also tracks query spend.
- **Single-vendor dependency.** Open States stays wired as a cross-check, and
  Tier-1 first-party adapters exist for the highest-value states — so no single
  source is a hard dependency.
- **CO bill-number format drift.** `colorado_bill_id()` is unit-tested and
  falls back to the raw LegiScan number if a number doesn't parse.
- **Double-ingest.** Mutually-exclusive state assignment (LegiScan states are
  removed from the OS sweep) plus content-hash dedup downstream.
