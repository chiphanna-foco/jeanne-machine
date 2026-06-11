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


def test_legiscan_normalize_colorado_bill():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    bill = {
        "bill_id": 1899123,
        "number": "HB1196",
        "change_hash": "abc123",
        "url": "https://legiscan.com/CO/bill/HB1196/2026",
        "status_date": "2026-02-10",
        "status": 1,
        "last_action_date": "2026-02-12",
        "last_action": "Introduced In House",
        "title": "Tenant Data Information",
        "description": "Concerning protections for tenant screening data.",
    }
    doc = adapter._normalize(bill, "CO", 2026)
    assert doc is not None
    assert doc.external_id == "legiscan-1899123"
    assert doc.state_code == "CO"
    assert doc.jurisdiction_level == "state"
    # Official CO display id surfaces so a search for "1196"/"HB26-1196" matches.
    assert "HB26-1196" in doc.title
    assert "Tenant Data Information" in doc.title
    assert doc.published_at == datetime(2026, 2, 12)
    assert doc.extra["legiscan_number"] == "HB1196"
    assert doc.extra["display_id"] == "HB26-1196"


def test_legiscan_normalize_skips_incomplete():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    assert adapter._normalize({"bill_id": 1, "number": "", "title": "x"}, "CO", 2026) is None
    assert adapter._normalize({"bill_id": None, "number": "HB1", "title": "x"}, "CO", 2026) is None


def test_legiscan_within_window():
    adapter = LegiScanAdapter(states=["CO"], api_key="dummy")
    assert adapter._within_window({"last_action_date": "2026-03-01"}, date(2026, 1, 1)) is True
    assert adapter._within_window({"last_action_date": "2025-12-01"}, date(2026, 1, 1)) is False
    # No date → kept (over-include rather than silently drop).
    assert adapter._within_window({}, date(2026, 1, 1)) is True
