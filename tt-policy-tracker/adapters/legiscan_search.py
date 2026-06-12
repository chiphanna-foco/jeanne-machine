"""LegiScan full-text SEARCH adapter — recall-first national discovery.

Why this exists: the masterlist-driven approach (adapters/legiscan.py) makes
US infer relevance from thin summaries ("Concerning tenant data information"),
which is how CO HB26-1196 — a signed tenant-screening law squarely inside
TurboTenant's product surface — was repeatedly missed. LegiScan already runs a
full-text index over every bill in the country. This adapter flips discovery:
run standing queries derived from TurboTenant's product surfaces against
``getSearchRaw state=ALL`` and let THEIR index find the bills; our LLM budget
then goes to analysis instead of reconstruction.

Recall properties:
  - Queries search full bill text nationally, not per-state summaries — a
    vaguely-titled bill matches on its body text.
  - ``since`` is deliberately ignored: a relevant law we never ingested should
    surface no matter how old it is within the current sessions (year=2).
    Incrementality comes from change_hash, not date windows.
  - The matched query terms are appended to raw_text ("Matched policy
    searches: ...") so the classifier sees WHY a bill was surfaced.

Quota: ~16 getSearchRaw calls per run + getBill only for new/changed matches
above min_relevance, capped per run (overflow is logged, never silent, and is
picked up next run since its change_hash stays unseen).
"""

import logging
from datetime import datetime

import httpx

from adapters.base import RawDoc
from adapters.legiscan import LegiScanAdapter
from config import settings

logger = logging.getLogger(__name__)

# Standing queries derived from TurboTenant's product surfaces (screening,
# applications, leases, payments, deposits, notices/evictions, listings,
# insurance) plus the core landlord-tenant policy areas. Overridable via
# LEGISCAN_SEARCH_QUERIES.
DEFAULT_QUERIES = [
    "landlord tenant",
    "security deposit",
    "eviction",
    "tenant screening",
    "rental application",
    "application fee",
    "rent control",
    "rent stabilization",
    "rent increase",
    "habitability",
    "lease agreement",
    "fair housing",
    "source of income",
    "rental registration",
    "mobile home park",
    "renters insurance",
]


class LegiScanSearchAdapter(LegiScanAdapter):
    """National discovery via LegiScan's full-text search engine."""

    @property
    def source_name(self) -> str:
        return "legiscan_search"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        queries: list[str] | None = None,
        api_key: str | None = None,
        seen_change_hashes: dict[int, str] | None = None,
        min_relevance: int | None = None,
        max_getbill: int | None = None,
    ):
        super().__init__(client=client, states=[], api_key=api_key,
                         seen_change_hashes=seen_change_hashes)
        self.queries = queries if queries is not None else settings.legiscan_search_queries_list
        self.min_relevance = (
            min_relevance if min_relevance is not None
            else settings.legiscan_search_min_relevance
        )
        self.max_getbill = (
            max_getbill if max_getbill is not None
            else settings.legiscan_search_max_getbill
        )

    async def discover_jurisdictions(self) -> list[dict]:
        return [{"name": "ALL", "level": "state", "state_code": None}]

    async def fetch_new_items(self, since: datetime) -> list[RawDoc]:
        """Run every standing query nationally, union the matches, getBill the
        new/changed ones, and normalize. ``since`` is intentionally unused —
        see module docstring (change_hash is the incremental mechanism)."""
        docs: list[RawDoc] = []
        stats: dict = {}

        if not self.api_key:
            logger.error("legiscan_search: no API key configured; skipping")
            self.last_run_stats = {"_search": {"error": "no API key configured"}}
            return docs

        # 1. Union matches across all standing queries.
        #    bill_id -> {change_hash, relevance, queries: [matched terms]}
        matches: dict[int, dict] = {}
        for q in self.queries:
            q_stats = {"hits": 0, "kept": 0, "error": None}
            try:
                payload = await self._get_json(
                    {"op": "getSearchRaw", "state": "ALL", "query": q}
                )
                results = self._search_results(payload)
                q_stats["hits"] = len(results)
                for r in results:
                    bid = r.get("bill_id")
                    rel = r.get("relevance", 0) or 0
                    if bid is None or rel < self.min_relevance:
                        continue
                    q_stats["kept"] += 1
                    m = matches.setdefault(
                        bid, {"change_hash": r.get("change_hash"), "relevance": rel, "queries": []}
                    )
                    m["queries"].append(q)
                    m["relevance"] = max(m["relevance"], rel)
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                logger.error(f"legiscan_search: query '{q}' failed: {msg}")
                q_stats["error"] = msg
            stats[q] = q_stats

        # 2. Drop bills whose change_hash we've already ingested (unchanged).
        new_bills = {
            bid: m for bid, m in matches.items()
            if self.seen_change_hashes.get(bid) != m["change_hash"]
        }
        skipped_unchanged = len(matches) - len(new_bills)

        # 3. Fetch detail for the new/changed ones, highest relevance first,
        #    bounded by max_getbill. Overflow is logged (never silent) and gets
        #    picked up next run — its change_hash remains unseen.
        ordered = sorted(new_bills.items(), key=lambda kv: -kv[1]["relevance"])
        overflow = max(0, len(ordered) - self.max_getbill)
        if overflow:
            logger.warning(
                f"legiscan_search: {overflow} matched bills beyond the "
                f"{self.max_getbill}-getBill cap deferred to next run"
            )
        fetched = 0
        detail_err = 0
        for bid, m in ordered[: self.max_getbill]:
            try:
                detail = await self._get_bill(bid)
                fetched += 1
            except Exception as e:
                detail_err += 1
                logger.error(
                    f"legiscan_search: getBill({bid}) failed: {type(e).__name__}: {str(e)[:150]}"
                )
                continue
            state = (detail.get("state") or "").upper()
            doc = self._normalize_detail(detail, state, None, m["change_hash"])
            if doc:
                # Tell the classifier WHY this bill surfaced — a match on
                # tenant/landlord search terms is itself relevance evidence,
                # especially when the summary text is boilerplate.
                doc.raw_text += f"\nMatched policy searches: {', '.join(m['queries'])}"
                doc.extra["matched_queries"] = m["queries"]
                doc.extra["search_relevance"] = m["relevance"]
                docs.append(doc)

        stats["_totals"] = {
            "matched_bills": len(matches),
            "skipped_unchanged": skipped_unchanged,
            "fetched": fetched,
            "detail_err": detail_err,
            "deferred_over_cap": overflow,
            "kept": len(docs),
        }
        self.last_run_stats = stats
        return docs

    @staticmethod
    def _search_results(payload: dict) -> list[dict]:
        """Extract result entries from a getSearchRaw payload.

        The manual's sample renders ``results`` as an array, but the live API
        has historically also used dict-keyed entries (like masterlist) and
        tucks a ``summary`` block alongside — handle all shapes defensively.
        """
        sr = payload.get("searchresult", {}) or {}
        raw = sr.get("results", sr)
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict) and "bill_id" in r]
        if isinstance(raw, dict):
            return [
                v for k, v in raw.items()
                if k != "summary" and isinstance(v, dict) and "bill_id" in v
            ]
        return []
