"""Tests for the act-now alert policy + compact Slack blocks."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from digest.slack import build_alert_blocks
from enrichment.alerting import alert_sort_key, should_alert

TODAY = datetime(2026, 6, 11)


def test_urgent_always_alerts():
    assert should_alert("urgent", None, TODAY) is True


def test_effective_soon_alerts_regardless_of_label():
    # Known effective date inside the 6-month window → alert even if "monitor".
    assert should_alert("monitor", datetime(2026, 9, 1), TODAY) is True
    assert should_alert("inform", datetime(2026, 7, 1), TODAY) is True


def test_recently_effective_alerts():
    # Binding now (effective 2 months ago, surfaced late) → still alert.
    assert should_alert("inform", datetime(2026, 4, 20), TODAY) is True


def test_speculative_and_distant_items_stay_quiet():
    # The user's rule: not approved + 6 months to react even if approved → no ping.
    assert should_alert("monitor", None, TODAY) is False          # moving, no date
    assert should_alert("inform", None, TODAY) is False           # early-stage/dead
    assert should_alert("inform", datetime(2027, 7, 1), TODAY) is False  # >6mo out
    assert should_alert("monitor", datetime(2025, 1, 1), TODAY) is False  # long past


def test_sort_puts_urgent_and_soonest_first():
    a = {"action_needed": "urgent", "effective_date": "2026-07-01", "impact_score": "med"}
    b = {"action_needed": "urgent", "effective_date": "2026-06-15", "impact_score": "low"}
    c = {"action_needed": "monitor", "effective_date": "2026-06-12", "impact_score": "high"}
    assert sorted([a, b, c], key=alert_sort_key) == [b, a, c]


def test_alert_blocks_compact_and_capped_footer():
    items = [
        {"title": "Colorado Enacts RUBS Regulations", "source_url": "https://leg.colorado.gov/bills/HB26-1013",
         "impact_score": "med", "effective_date": "2026-03-26", "impact_reasoning": "Update utility billing practices."},
    ]
    blocks = build_alert_blocks(items, tracked_count=12)
    text = str(blocks)
    assert "1 law update needing attention" in text
    assert "effective 2026-03-26" in text
    assert "12 more tracked on the watchlist" in text
    # Compact: one section of lines, not one giant block per item.
    assert len(blocks) == 3  # header + lines + footer


def test_alert_blocks_zero_tracked_footer_still_links_dashboard():
    blocks = build_alert_blocks([], tracked_count=0)
    assert "dashboard" in str(blocks)
