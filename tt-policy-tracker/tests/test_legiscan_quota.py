"""LegiScan query budget: hash cache, search cache, pacing, and the over-limit stop.

Pure tests with a fake HTTP client; no network, no database.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
# LegiScan's polite pacing sleeps 0.3 s per call; not needed here.
import adapters.legiscan as legiscan_mod  # noqa: E402
from adapters.legiscan import (  # noqa: E402
    LegiScanAdapter,
    getbill_allowance,
    is_quota_message,
)
from adapters.legiscan_search import LegiScanSearchAdapter  # noqa: E402

legiscan_mod.LEGISCAN_MIN_INTERVAL = 0

OVER_LIMIT = (
    "API key has exceeded maximum query count for November 2026 (10,044 of 10,000); "
    "limit resets December 1st"
)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeLegiScan:
    """Answers getSearchRaw / getBill / getMasterList; records every call."""

    def __init__(self, search_hits=None, over_limit=False):
        self.calls: list[dict] = []
        self.search_hits = search_hits or []
        self.over_limit = over_limit

    async def get(self, url, params=None, headers=None):
        self.calls.append(dict(params))
        if self.over_limit:
            return _Resp({"status": "ERROR", "alert": {"message": OVER_LIMIT}})
        op = params["op"]
        if op == "getSearchRaw":
            return _Resp({"status": "OK", "searchresult": {"results": self.search_hits}})
        if op == "getBill":
            bid = params["id"]
            return _Resp({"status": "OK", "bill": {
                "bill_id": bid, "bill_number": f"HB{bid}", "state": "CO",
                "title": f"Bill {bid}", "change_hash": f"h{bid}",
                "history": [{"date": "2026-11-01", "action": "Introduced"}],
            }})
        if op == "getMasterList":
            return _Resp({"status": "OK", "masterlist": {
                "session": {"year_start": 2026},
                "0": {"bill_id": 7, "number": "HB7", "change_hash": "h7",
                      "title": "Residential landlord tenant security deposits",
                      "description": "Concerning rental housing", "last_action_date": "2026-11-01"},
            }})
        raise AssertionError(op)

    def ops(self, op):
        return [c for c in self.calls if c["op"] == op]


def _search(fake, **kw):
    kw.setdefault("api_key", "dummy")
    kw.setdefault("queries", ["eviction", "security deposit"])
    kw.setdefault("min_relevance", 50)
    kw.setdefault("max_getbill", 300)
    return LegiScanSearchAdapter(client=fake, **kw)


def _run(adapter):
    return asyncio.run(adapter.fetch_new_items(datetime(2026, 1, 1)))


HITS = [
    {"relevance": 90, "bill_id": 1, "change_hash": "h1"},
    {"relevance": 80, "bill_id": 2, "change_hash": "h2"},
    {"relevance": 10, "bill_id": 3, "change_hash": "h3"},  # below min_relevance
]


# ── hash cache ────────────────────────────────────────────────────────────

def test_unchanged_bills_are_not_fetched_again():
    fake = _FakeLegiScan(HITS)
    a = _search(fake, seen_change_hashes={1: "h1", 2: "h2"})
    _run(a)
    assert fake.ops("getBill") == []


def test_changed_bill_is_fetched_and_its_hash_is_reported():
    fake = _FakeLegiScan(HITS)
    a = _search(fake, seen_change_hashes={1: "h1", 2: "OLD"})
    _run(a)
    assert [c["id"] for c in fake.ops("getBill")] == [2]
    # Reported for the legiscan_bill cache whether or not ingest keeps the doc:
    # this is what stops the "same 300 bills every run" loop.
    assert a.fetched_hashes == {2: "h2"}


def test_second_run_with_reported_hashes_fetches_nothing():
    fake = _FakeLegiScan(HITS)
    first = _search(fake, seen_change_hashes={})
    _run(first)
    assert len(fake.ops("getBill")) == 2
    fake2 = _FakeLegiScan(HITS)
    second = _search(fake2, seen_change_hashes=dict(first.fetched_hashes))
    _run(second)
    assert fake2.ops("getBill") == []


def test_hit_without_change_hash_is_not_refetched_forever():
    hits = [{"relevance": 90, "bill_id": 1}]
    fake = _FakeLegiScan(hits)
    _run(_search(fake, seen_change_hashes={1: "h1"}))
    assert fake.ops("getBill") == []


def test_masterlist_adapter_reports_fetched_hashes():
    fake = _FakeLegiScan()
    a = LegiScanAdapter(client=fake, states=["co"], api_key="dummy")
    _run(a)
    assert a.fetched_hashes == {7: "h7"}


# ── search cache ──────────────────────────────────────────────────────────

def test_cached_searches_cost_nothing():
    fake = _FakeLegiScan(HITS)
    cached = {"eviction": HITS[:1], "security deposit": HITS[1:]}
    a = _search(fake, seen_change_hashes={1: "h1", 2: "h2"}, cached_searches=cached)
    _run(a)
    assert fake.calls == []
    assert a.last_run_stats["_totals"]["searches_cached"] == 2
    assert a.fresh_searches == {}


def test_fresh_searches_are_returned_for_caching():
    fake = _FakeLegiScan(HITS)
    a = _search(fake, seen_change_hashes={1: "h1", 2: "h2"},
                cached_searches={"eviction": HITS})
    _run(a)
    assert [c["query"] for c in fake.ops("getSearchRaw")] == ["security deposit"]
    assert set(a.fresh_searches) == {"security deposit"}
    assert a.fresh_searches["security deposit"][0] == {
        "bill_id": 1, "change_hash": "h1", "relevance": 90,
    }


# ── over the monthly limit ────────────────────────────────────────────────

def test_quota_message_detection():
    assert is_quota_message(OVER_LIMIT)
    assert not is_quota_message("Unknown bill id")
    assert not is_quota_message(None)


def test_over_limit_stops_the_whole_run_after_one_call():
    fake = _FakeLegiScan(HITS, over_limit=True)
    a = _search(fake, queries=["a", "b", "c", "d"])
    docs = _run(a)
    assert docs == []
    # One call, not 16 + 300: every later call would fail and still count.
    assert len(fake.calls) == 1
    assert a.quota_exhausted
    assert "monthly limit reached" in a.quota_message
    assert a.last_run_stats["_totals"]["stopped"]


def test_over_limit_on_masterlist_skips_remaining_states():
    fake = _FakeLegiScan(over_limit=True)
    a = LegiScanAdapter(client=fake, states=["co", "wa", "or"], api_key="dummy")
    _run(a)
    assert len(fake.calls) == 1
    assert a.last_run_stats["WA"]["list_status"] == "skipped"


def test_own_budget_stop_also_stops_the_run():
    fake = _FakeLegiScan(HITS)
    a = _search(fake, queries=["a", "b", "c"], budget_remaining=1)
    _run(a)
    assert len(fake.calls) == 1
    assert a.quota_exhausted


# ── pacing ────────────────────────────────────────────────────────────────

def test_getbill_allowance_spreads_budget_over_month():
    # 8,000 left on the 1st of a 30-day month, 16 searches to send.
    assert getbill_allowance(8000, 30, 300, reserve=16) == 266
    # Late in the month with little left, the cap shrinks.
    assert getbill_allowance(300, 3, 300, reserve=16) == 94
    # Never above the configured per-run max, never negative.
    assert getbill_allowance(100000, 1, 300) == 300
    assert getbill_allowance(5, 10, 300, reserve=16) == 0
    assert getbill_allowance(None, 10, 300) == 300


def test_cap_defers_overflow_highest_relevance_first():
    fake = _FakeLegiScan(HITS)
    a = _search(fake, max_getbill=1)
    _run(a)
    assert [c["id"] for c in fake.ops("getBill")] == [1]
    assert a.last_run_stats["_totals"]["deferred_over_cap"] == 1


def test_effective_budget_never_exceeds_85_percent_of_plan():
    from config import Settings

    s = Settings(legiscan_monthly_budget=27000, legiscan_plan_limit=10000)
    assert s.legiscan_effective_budget == 8500
    s = Settings(legiscan_monthly_budget=6000, legiscan_plan_limit=10000)
    assert s.legiscan_effective_budget == 6000
