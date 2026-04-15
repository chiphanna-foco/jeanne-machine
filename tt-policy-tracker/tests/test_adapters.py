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
