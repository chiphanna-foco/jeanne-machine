"""Unit tests for feedback annotation + suppression (pure)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment.feedback import annotate_and_suppress, precision

ITEMS = [
    {"id": 1, "source_url": "https://leg.colorado.gov/bills/HB26-1045"},   # CO:HB1045:2026
    {"id": 2, "source_url": "https://legiscan.com/CO/bill/HB1284/2026"},   # CO:HB1284:2026
    {"id": 3, "source_url": "https://legiscan.com/CO/bill/HB1106/2026"},   # CO:HB1106:2026
]

def test_thumbs_down_is_suppressed():
    fb = {"CO:HB1284:2026": "down"}
    out = annotate_and_suppress(ITEMS, fb)
    ids = [i["id"] for i in out]
    assert 2 not in ids and len(out) == 2
    # surviving items carry their (None) label + bill_key
    assert out[0]["feedback"] is None
    assert out[0]["bill_key"] == "CO:HB1045:2026"

def test_up_and_watching_are_annotated_not_hidden():
    fb = {"CO:HB1045:2026": "up", "CO:HB1106:2026": "watching"}
    out = annotate_and_suppress(ITEMS, fb)
    assert len(out) == 3
    by = {i["id"]: i["feedback"] for i in out}
    assert by == {1: "up", 2: None, 3: "watching"}

def test_include_dismissed_keeps_downs():
    fb = {"CO:HB1284:2026": "down"}
    out = annotate_and_suppress(ITEMS, fb, include_dismissed=True)
    assert len(out) == 3
    assert next(i for i in out if i["id"] == 2)["feedback"] == "down"

def test_precision():
    assert precision(["up", "up", "down"]) == 2 / 3
    assert precision(["watching"]) is None
    assert precision([]) is None
