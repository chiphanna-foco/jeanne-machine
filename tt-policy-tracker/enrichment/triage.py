"""Triage + de-duplication for policy items.

Two jobs, both pure (no DB), so they're easy to test and reuse from the API,
the digest, and any UI:

1. De-dup. The same bill can land more than once — e.g. a LegiScan bill
   ingested before and after the getBill change (different external_ids), or
   the same bill seen via LegiScan and Open States. We collapse them to one
   canonical bill, preferring the richest/most-recent record.

2. Triage. Bucket each item by how much it actually demands attention, using
   the classifier's own `action_needed` (urgent/monitor/inform) plus the
   `effective_date` horizon, so "what do I worry about in the next 3-6 months"
   is separated from "just keep an eye on it" and dead-bill noise.
"""

import re
from datetime import datetime, timedelta

# Map the state hints we can see in a source URL to a two-letter code.
_DOMAIN_STATE = {"colorado": "CO"}  # extend as more first-party sources are added


def canonical_bill_key(source_url: str | None, external_id: str | None = None) -> str | None:
    """A source-independent identity for a bill, e.g. ``CO:HB1045:2026``.

    Normalizes the three URL shapes we ingest so duplicates of the same bill
    collapse to one key:
      - https://legiscan.com/CO/bill/HB1045/2026        → CO:HB1045:2026
      - https://leg.colorado.gov/bills/HB26-1045        → CO:HB1045:2026
      - https://openstates.org/co/bills/2025A/HB25-1196 → CO:HB1196:2025

    Returns None when no bill identity can be parsed (item is left as-is).
    """
    u = (source_url or "").strip()
    if not u:
        return None

    # State: explicit /XX/ path (legiscan, openstates) or a known state domain.
    state = None
    m = re.search(r"(?:legiscan\.com|openstates\.org)/([A-Za-z]{2})\b", u)
    if m:
        state = m.group(1).upper()
    else:
        for dom, code in _DOMAIN_STATE.items():
            if dom in u:
                state = code
                break

    # Bill token: chamber letters then the number, optionally with a 2-digit
    # session-year prefix (HB26-1045) or trailing year path (/HB1045/2026).
    bm = re.search(r"\b([A-Za-z]{1,4})\s*0*(\d{2})-0*(\d+)\b", u)  # HB26-1045
    year = None
    if bm:
        chamber, yy, num = bm.group(1).upper(), bm.group(2), bm.group(3)
        year = 2000 + int(yy)
    else:
        bm = re.search(r"\b([A-Za-z]{1,4})\s*0*(\d+)\b", u)  # HB1045 / SB054
        if not bm:
            return None
        chamber, num = bm.group(1).upper(), bm.group(2)
        ym = re.search(r"/(\d{4})A?(?:/|$)", u)  # /2026 or /2025A
        if ym:
            year = int(ym.group(1))

    num = str(int(num))  # normalize leading zeros: 054 -> 54
    parts = [p for p in (state, f"{chamber}{num}", str(year) if year else None) if p]
    return ":".join(parts)


def dedupe_items(items: list[dict]) -> tuple[list[dict], int]:
    """Collapse items that refer to the same bill. Returns (kept, removed_count).

    Among duplicates we keep the "best" record: an official first-party link
    (leg.<state>.gov) wins over an aggregator, then the most recently
    discovered (so the richer getBill-era record beats the older thin one).
    Items with no parseable bill key are always kept.
    """
    def quality(it: dict) -> tuple:
        u = it.get("source_url") or ""
        official = 1 if re.search(r"leg\.[a-z]+\.gov", u) else 0
        return (official, it.get("discovered_at") or "")

    best: dict[str, dict] = {}
    passthrough: list[dict] = []
    removed = 0
    for it in items:
        key = canonical_bill_key(it.get("source_url"), it.get("external_id"))
        if key is None:
            passthrough.append(it)
            continue
        if key not in best:
            best[key] = it
        else:
            removed += 1
            if quality(it) > quality(best[key]):
                best[key] = it
    return list(best.values()) + passthrough, removed


def make_effective_sort_key(today: datetime):
    """Key factory for "goes into law soonest" ordering, FUTURE-first.

    What the legal team means by this sort: "what's about to become binding?"
      group 0 — effective today or later, soonest first (the upcoming wave)
      group 1 — already effective, most recent first (recently became law)
      group 2 — no effective date, newest discovered first (watchlist tail)

    A plain ascending date sort gets this wrong — it surfaces decade-old laws
    first (a 2016 federal act outranked next month's state law).
    """
    today_s = today.strftime("%Y-%m-%d")

    def key(item: dict) -> tuple:
        eff = item.get("effective_date")
        if eff:
            e = str(eff)[:10]
            if e >= today_s:
                return (0, e, "")
            return (1, _invert_str(e), "")
        disc = str(item.get("discovered_at") or "")
        return (2, "", _invert_str(disc))

    return key


def _invert_str(s: str) -> str:
    """Map a string so ascending sort yields descending original order."""
    return "".join(chr(255 - ord(c)) if ord(c) < 255 else c for c in s)


# action_needed → triage bucket. The classifier already encodes urgency here.
_BUCKET = {"urgent": "act_now", "monitor": "monitor", "inform": "fyi", None: "fyi"}


def triage_item(item: dict, today: datetime, horizon_months: int = 6) -> dict:
    """Annotate an item with a triage `bucket` and an effective-date `horizon`.

    bucket: act_now | monitor | fyi  (from action_needed)
    horizon (act_now only): effective_soon (lands within the window) |
            recently_effective (last 90d) | enacted | none
    """
    bucket = _BUCKET.get(item.get("action_needed"), "fyi")

    horizon = "none"
    eff = item.get("effective_date")
    if eff:
        try:
            ed = datetime.fromisoformat(str(eff).replace("Z", "+00:00")).replace(tzinfo=None)
            window = today + timedelta(days=horizon_months * 30)
            if today <= ed <= window:
                horizon = "effective_soon"
            elif today - timedelta(days=90) <= ed < today:
                horizon = "recently_effective"
            elif ed > window:
                horizon = "future"
            else:
                horizon = "enacted"
        except (ValueError, TypeError):
            pass

    return {**item, "bucket": bucket, "horizon": horizon}


def triage(items: list[dict], today: datetime, horizon_months: int = 6) -> dict:
    """De-dup, bucket, and sort items for a prioritized 'what matters' view.

    Returns {act_now, monitor, fyi, counts, deduped_removed}. Within act_now,
    soonest-effective bills sort first; otherwise highest impact first.
    """
    kept, removed = dedupe_items(items)
    annotated = [triage_item(it, today, horizon_months) for it in kept]

    imp = {"high": 0, "med": 1, "low": 2}
    hz = {"effective_soon": 0, "future": 1, "recently_effective": 2, "enacted": 3, "none": 4}

    def act_sort(it):
        return (hz.get(it["horizon"], 4), imp.get(it.get("impact_score"), 3))

    buckets: dict[str, list] = {"act_now": [], "monitor": [], "fyi": []}
    for it in annotated:
        buckets[it["bucket"]].append(it)
    buckets["act_now"].sort(key=act_sort)
    buckets["monitor"].sort(key=lambda it: imp.get(it.get("impact_score"), 3))
    buckets["fyi"].sort(key=lambda it: imp.get(it.get("impact_score"), 3))

    return {
        **buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
        "deduped_removed": removed,
    }
