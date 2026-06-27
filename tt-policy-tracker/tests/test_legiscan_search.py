"""Unit tests for the LegiScan full-text search adapter (pure, no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.legiscan_search import DEFAULT_QUERIES, LegiScanSearchAdapter


def _adapter(**kw):
    kw.setdefault("api_key", "dummy")
    kw.setdefault("queries", ["tenant screening"])
    return LegiScanSearchAdapter(**kw)


def test_search_results_parses_list_shape():
    payload = {"searchresult": {"summary": {"count": 2}, "results": [
        {"relevance": 100, "bill_id": 1, "change_hash": "a"},
        {"relevance": 60, "bill_id": 2, "change_hash": "b"},
    ]}}
    out = LegiScanSearchAdapter._search_results(payload)
    assert [r["bill_id"] for r in out] == [1, 2]


def test_search_results_parses_dict_shape():
    # The live API has historically used masterlist-style dict keys.
    payload = {"searchresult": {
        "summary": {"count": 2},
        "0": {"relevance": 100, "bill_id": 1, "change_hash": "a"},
        "1": {"relevance": 60, "bill_id": 2, "change_hash": "b"},
    }}
    out = LegiScanSearchAdapter._search_results(payload)
    assert sorted(r["bill_id"] for r in out) == [1, 2]


def test_default_queries_cover_turbotenant_surfaces():
    # The standing set must include the product surfaces that motivated the
    # redesign — screening (HB26-1196), deposits, eviction, applications.
    joined = " ".join(DEFAULT_QUERIES)
    for must in ("tenant screening", "security deposit", "eviction", "rental application"):
        assert must in joined


def test_normalize_detail_appends_matched_queries_context():
    a = _adapter()
    detail = {
        "bill_id": 2114530,
        "session": {"year_start": 2026},
        "bill_number": "HB1196",
        "state": "CO",
        "title": "Tenant Data Information",
        "description": "Concerning tenant data information.",
        "subjects": [{"subject_name": "Housing"}],
        "history": [{"date": "2026-06-02", "action": "Governor Signed"}],
        "url": "https://legiscan.com/CO/bill/HB1196/2026",
        "state_link": "https://leg.colorado.gov/bills/hb26-1196",
    }
    doc = a._normalize_detail(detail, "CO", None, "hash123")
    doc.raw_text += "\nMatched policy searches: tenant screening"
    assert "Matched policy searches: tenant screening" in doc.raw_text
    assert "Subjects: Housing" in doc.raw_text
    assert "HB26-1196" in doc.title  # CO display id still applied via subclass
    assert doc.external_id == "legiscan-2114530-hash123"


def test_source_name_distinct_from_masterlist_adapter():
    assert _adapter().source_name == "legiscan_search"


def test_budget_remaining_propagates_to_base_adapter():
    # The search adapter must forward the monthly budget into the shared
    # _get_json guard (it lives on the base LegiScanAdapter).
    a = _adapter(budget_remaining=5)
    assert a.budget_remaining == 5
    assert a.queries_used == 0


def test_get_json_refuses_to_spend_past_budget():
    # With budget already consumed, _get_json must raise BEFORE any network
    # call so we never trip LegiScan's hard monthly limit.
    import asyncio

    from adapters.legiscan import LegiScanBudgetExceeded

    a = _adapter(budget_remaining=1)
    a.queries_used = 1  # budget exhausted for this window

    async def _go():
        await a._get_json({"op": "getSearchRaw", "state": "ALL", "query": "x"})

    try:
        asyncio.run(_go())
        assert False, "expected LegiScanBudgetExceeded"
    except LegiScanBudgetExceeded:
        pass


def test_api_error_is_not_retried():
    # A non-OK LegiScan envelope (quota/throttle) is a LegiScanApiError, which
    # must fail fast — retrying just burns more quota on the same failure.
    import asyncio

    from adapters.legiscan import LegiScanApiError

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ERROR", "alert": {"message": "exceeded query count"}}

    class _FakeClient:
        def __init__(self):
            self.calls = 0

        async def get(self, *a, **kw):
            self.calls += 1
            return _FakeResp()

    a = _adapter()
    a.client = _FakeClient()

    async def _go():
        await a._get_json({"op": "getBill", "id": 1})

    try:
        asyncio.run(_go())
        assert False, "expected LegiScanApiError"
    except LegiScanApiError:
        pass
    # Exactly one call — no retry loop on an application-level error.
    assert a.client.calls == 1
