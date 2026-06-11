"""Unit tests for triage + de-duplication (pure, no DB)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.triage import canonical_bill_key, dedupe_items, triage, triage_item


def test_canonical_key_collapses_source_variants():
    # The same bill seen three ways must normalize to one key.
    a = canonical_bill_key("https://leg.colorado.gov/bills/HB26-1045")
    b = canonical_bill_key("https://legiscan.com/CO/bill/HB1045/2026")
    assert a == b == "CO:HB1045:2026"
    # Leading zeros normalized: SB054 == SB26-054.
    assert canonical_bill_key("https://legiscan.com/CO/bill/SB054/2026") == "CO:SB54:2026"
    assert canonical_bill_key("https://leg.colorado.gov/bills/SB26-054") == "CO:SB54:2026"


def test_canonical_key_distinguishes_year_and_chamber():
    assert canonical_bill_key("https://openstates.org/co/bills/2025A/HB25-1196/") == "CO:HB1196:2025"
    # Different session year → different bill.
    assert canonical_bill_key("https://legiscan.com/CO/bill/HB1196/2026") == "CO:HB1196:2026"
    assert canonical_bill_key("") is None
    assert canonical_bill_key(None) is None


def test_dedupe_prefers_official_link():
    items = [
        {"id": 1, "source_url": "https://legiscan.com/CO/bill/HB1045/2026", "discovered_at": "2026-06-11T18:00:00"},
        {"id": 2, "source_url": "https://leg.colorado.gov/bills/HB26-1045", "discovered_at": "2026-06-11T17:00:00"},
    ]
    kept, removed = dedupe_items(items)
    assert removed == 1
    assert len(kept) == 1
    # Official leg.colorado.gov link wins even though it was discovered earlier.
    assert kept[0]["id"] == 2


def test_dedupe_keeps_unparseable_items():
    items = [
        {"id": 1, "source_url": "https://example.com/whatever"},
        {"id": 2, "source_url": "https://example.com/another"},
    ]
    kept, removed = dedupe_items(items)
    assert removed == 0
    assert len(kept) == 2


def test_triage_buckets_by_action_needed():
    today = datetime(2026, 6, 11)
    items = [
        {"id": 1, "action_needed": "urgent", "impact_score": "high",
         "effective_date": "2026-05-28T00:00:00", "source_url": "https://leg.colorado.gov/bills/HB26-1045"},
        {"id": 2, "action_needed": "monitor", "impact_score": "high",
         "effective_date": None, "source_url": "https://openstates.org/co/bills/2025A/HB25-1240/"},
        {"id": 3, "action_needed": "inform", "impact_score": "low",
         "effective_date": None, "source_url": "https://legiscan.com/CO/bill/HB1106/2026"},
    ]
    res = triage(items, today)
    assert res["counts"] == {"act_now": 1, "monitor": 1, "fyi": 1}
    assert res["act_now"][0]["id"] == 1
    assert res["act_now"][0]["horizon"] == "recently_effective"


def test_triage_dedupes_before_bucketing():
    today = datetime(2026, 6, 11)
    # Same bill twice (v1 legiscan + phase3 leg.co) → one act_now item.
    items = [
        {"id": 1, "action_needed": "urgent", "impact_score": "med",
         "effective_date": "2026-07-01T00:00:00",
         "source_url": "https://legiscan.com/CO/bill/HB1013/2026", "discovered_at": "2026-06-11T17:00:00"},
        {"id": 2, "action_needed": "urgent", "impact_score": "med",
         "effective_date": "2026-07-01T00:00:00",
         "source_url": "https://leg.colorado.gov/bills/HB26-1013", "discovered_at": "2026-06-11T19:00:00"},
    ]
    res = triage(items, today)
    assert res["deduped_removed"] == 1
    assert res["counts"]["act_now"] == 1
    # Effective 2026-07-01 is within 6 months of today → effective_soon.
    assert res["act_now"][0]["horizon"] == "effective_soon"


def test_triage_item_horizon_classification():
    today = datetime(2026, 6, 11)
    soon = triage_item({"action_needed": "urgent", "effective_date": "2026-09-01T00:00:00"}, today)
    assert soon["horizon"] == "effective_soon"
    recent = triage_item({"action_needed": "urgent", "effective_date": "2026-05-01T00:00:00"}, today)
    assert recent["horizon"] == "recently_effective"
    far = triage_item({"action_needed": "urgent", "effective_date": "2027-06-01T00:00:00"}, today)
    assert far["horizon"] == "future"
