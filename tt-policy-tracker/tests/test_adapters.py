"""Unit tests for adapter base class and normalization logic."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.base import BaseAdapter, RawDoc


def test_raw_doc_creation():
    doc = RawDoc(
        external_id="test-001",
        source_name="test",
        title="Test Document",
        url="https://example.com",
        raw_text="This is a test document about security deposits.",
        jurisdiction_name="Colorado",
        jurisdiction_level="state",
        state_code="CO",
        published_at=datetime(2026, 4, 15),
    )
    assert doc.external_id == "test-001"
    assert doc.state_code == "CO"
    assert doc.jurisdiction_level == "state"
    assert doc.extra == {}


def test_raw_doc_defaults():
    doc = RawDoc(
        external_id="test-002",
        source_name="test",
        title="Minimal Doc",
        url="",
        raw_text="text",
        jurisdiction_name="US",
        jurisdiction_level="federal",
    )
    assert doc.state_code is None
    assert doc.published_at is None
    assert doc.extra == {}


def test_base_adapter_is_abstract():
    """BaseAdapter should not be instantiable directly."""
    try:
        BaseAdapter()
        assert False, "Should have raised TypeError"
    except TypeError:
        pass


# --- LegiScan adapter (pure normalization, no network) ---

from datetime import date

from adapters.legiscan import LegiScanAdapter, colorado_bill_id


def test_colorado_bill_id_adds_year_infix():
    # LegiScan reports HB1196; Colorado publishes HB26-1196 for the 2026 session.
    assert colorado_bill_id("HB1196", 2026) == "HB26-1196"
    assert colorado_bill_id("SB1", 2025) == "SB25-1"
    assert colorado_bill_id("HJR1001", 2026) == "HJR26-1001"


def test_colorado_bill_id_passthrough_when_unparseable():
    assert colorado_bill_id("HB1196", None) == "HB1196"
    assert colorado_bill_id("WEIRD", 2026) == "WEIRD"


def _hb1196_detail():
    """A getBill-shaped payload for CO HB26-1196 (boilerplate description, but a
    Housing subject tag + action history — the real relevance signal)."""
    return {
        "bill_id": 2114530,
        "change_hash": "abcdef0123456789abcdef0123456789",
        "session": {"year_start": 2026},
        "bill_number": "HB1196",
        "state": "CO",
        "title": "Tenant Data Information",
        "description": "Concerning tenant data information.",
        "subjects": [{"subject_id": 1, "subject_name": "Housing"}],
        "status": 4,
        "status_date": "2026-05-20",
        "url": "https://legiscan.com/CO/bill/HB1196/2026",
        "state_link": "https://leg.colorado.gov/bills/hb26-1196",
        "history": [
            {"date": "2026-02-10", "action": "Introduced In House"},
            {"date": "2026-05-15", "action": "Sent to the Governor"},
            {"date": "2026-05-20", "action": "Governor Signed"},
        ],
    }


def test_legiscan_normalize_detail_folds_subjects_and_history():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    doc = adapter._normalize_detail(_hb1196_detail(), "CO", 2026, "abcdef0123456789abcdef0123456789")
    assert doc is not None
    # change_hash embedded in external_id for the seen-cache round-trip.
    assert doc.external_id == "legiscan-2114530-abcdef0123456789abcdef0123456789"
    # Official CO display id surfaces so a search for "1196"/"HB26-1196" matches.
    assert "HB26-1196" in doc.title
    # The decisive signals the masterlist lacked are now in the text.
    assert "Subjects: Housing" in doc.raw_text
    assert "Governor Signed" in doc.raw_text
    # Nicer jurisdiction name + official state link preferred.
    assert doc.jurisdiction_name == "Colorado"
    assert doc.url == "https://leg.colorado.gov/bills/hb26-1196"
    assert doc.extra["subjects"] == ["Housing"]
    assert doc.extra["legiscan_url"] == "https://legiscan.com/CO/bill/HB1196/2026"
    assert doc.published_at == datetime(2026, 5, 20)


def test_legiscan_normalize_detail_skips_incomplete():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    assert adapter._normalize_detail({"bill_id": 1, "bill_number": "", "title": "x"}, "CO", 2026, "h") is None
    assert adapter._normalize_detail({"bill_id": None, "bill_number": "HB1", "title": "x"}, "CO", 2026, "h") is None


def test_legiscan_is_candidate_prescreen():
    # HB26-1196's thin summary still mentions "Tenant" → passes the prescreen,
    # so it earns a getBill (where the Housing subject confirms relevance).
    assert LegiScanAdapter._is_candidate(
        {"number": "HB1196", "title": "Tenant Data Information",
         "description": "Concerning tenant data information."}
    ) is True
    # An off-topic bill with no housing keyword is screened out (no getBill spend).
    assert LegiScanAdapter._is_candidate(
        {"number": "HB1000", "title": "Wildfire Mitigation Funding",
         "description": "Concerning forest management grants."}
    ) is False


def test_legiscan_within_window():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    assert adapter._within_window({"last_action_date": "2026-03-01"}, date(2026, 1, 1)) is True
    assert adapter._within_window({"last_action_date": "2025-12-01"}, date(2026, 1, 1)) is False
    # No date → kept (over-include rather than silently drop).
    assert adapter._within_window({}, date(2026, 1, 1)) is True
