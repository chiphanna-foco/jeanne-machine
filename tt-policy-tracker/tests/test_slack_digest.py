"""Unit tests for the compact Slack digest blocks.

The digest must stay skimmable even after a backfill week dumps 100+ items:
one line per bill, hard caps per bucket, FYI as a count, no summaries.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from digest.slack import (
    DIGEST_ACT_NOW_LINES,
    DIGEST_MONITOR_LINES,
    MAX_BLOCKS,
    _digest_line,
    build_compact_digest_blocks,
)
from enrichment.triage import triage


def make_item(i: int, action: str = "inform", **over) -> dict:
    item = {
        "id": i,
        "title": f"Bill number {i} does something",
        "summary": "A long summary that should never appear in the digest." * 5,
        "impact_score": "high",
        "impact_reasoning": "REASONING_SENTINEL should never appear in the digest.",
        "action_needed": action,
        "source_url": f"https://legiscan.com/CO/bill/HB{1000 + i}/2026",
        "effective_date": None,
        "discovered_at": f"2026-06-{(i % 28) + 1:02d}T00:00:00",
    }
    item.update(over)
    return item


def all_text(blocks: list[dict]) -> str:
    return json.dumps(blocks)


def test_one_line_per_bill_no_summaries():
    items = [make_item(1, "urgent"), make_item(2, "monitor"), make_item(3, "inform")]
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    text = all_text(blocks)
    # urgent + monitor items are listed by title; summaries/reasoning never appear
    assert "Bill number 1" in text
    assert "Bill number 2" in text
    assert "long summary" not in text
    assert "REASONING_SENTINEL" not in text
    # fyi items are counted, not listed
    assert "Bill number 3" not in text
    assert "1 FYI item" in text


def test_buckets_capped_with_overflow_note():
    items = [make_item(i, "urgent") for i in range(40)]
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    text = all_text(blocks)
    listed = sum(1 for i in range(40) if f"Bill number {i} " in text)
    assert listed == DIGEST_ACT_NOW_LINES
    assert f"and {40 - DIGEST_ACT_NOW_LINES} more" in text
    assert "dashboard" in text


def test_block_count_stays_under_slack_limit_with_huge_backlog():
    # The failure mode that prompted this format: 124 'high impact' items.
    items = (
        [make_item(i, "urgent") for i in range(50)]
        + [make_item(100 + i, "monitor") for i in range(50)]
        + [make_item(200 + i, "inform") for i in range(24)]
    )
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    assert len(blocks) <= MAX_BLOCKS
    for b in blocks:
        if b["type"] == "section":
            assert len(b["text"]["text"]) <= 3000


def test_monitor_cap_independent_of_act_now():
    items = [make_item(i, "monitor") for i in range(30)]
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    text = all_text(blocks)
    listed = sum(1 for i in range(30) if f"Bill number {i} " in text)
    assert listed == DIGEST_MONITOR_LINES


def test_empty_digest():
    triaged = triage([], datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "daily", "Jun 12 – Jun 13, 2026")
    assert "No new policy items" in all_text(blocks)


def test_header_context_includes_counts_and_suppressed():
    items = [make_item(1, "urgent"), make_item(2, "inform")]
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(
        triaged, "weekly", "Jun 06 – Jun 13, 2026", suppressed=3
    )
    text = all_text(blocks)
    assert "2 items" in text
    assert "3 dismissed hidden" in text


def test_digest_line_format():
    line = _digest_line(
        {
            "title": "Colorado caps deposits",
            "source_url": "https://legiscan.com/CO/bill/HB1045/2026",
            "action_needed": "urgent",
            "effective_date": "2026-09-01T00:00:00",
            "bill_key": "CO:HB1045:2026",
        }
    )
    assert "*CO HB1045*" in line
    assert "<https://legiscan.com/CO/bill/HB1045/2026|Colorado caps deposits>" in line
    assert "effective 2026-09-01" in line
