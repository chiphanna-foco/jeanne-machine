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
    DIGEST_WATCH_LINES,
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
    items = [
        make_item(1, "urgent"),
        make_item(2, "monitor"),
        make_item(3, "inform", impact_score="low"),
    ]
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    text = all_text(blocks)
    # urgent + monitor items are listed by title; summaries/reasoning never appear
    assert "Bill number 1" in text
    assert "Bill number 2" in text
    assert "long summary" not in text
    assert "REASONING_SENTINEL" not in text
    # low-impact fyi items are counted, not listed
    assert "Bill number 3" not in text
    assert "1 FYI item" in text
    assert "Worth watching" not in text


def test_worth_watching_lists_top_med_high_fyi():
    # Off-season shape: nothing urgent or moving, a pile of early-stage bills.
    items = (
        [make_item(i, "inform", impact_score="med") for i in range(1, 4)]
        + [make_item(10 + i, "inform", impact_score="high") for i in range(1, 5)]
        + [make_item(20 + i, "inform", impact_score="low") for i in range(1, 9)]
    )
    triaged = triage(items, datetime(2026, 6, 13))
    blocks = build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026")

    text = all_text(blocks)
    assert "Worth watching" in text
    listed = [i for i in range(1, 29) if f"Bill number {i} " in text]
    assert len(listed) == DIGEST_WATCH_LINES
    # all 4 high-impact bills make the cut before any med one
    assert all(f"Bill number {10 + i} " in text for i in range(1, 5))
    assert not any(f"Bill number {20 + i} " in text for i in range(1, 9))
    # 15 fyi total, 5 listed
    assert "10 other FYI items" in text
    assert "15 items" in text


def test_worth_watching_absent_when_all_fyi_low():
    items = [make_item(i, "inform", impact_score="low") for i in range(5)]
    triaged = triage(items, datetime(2026, 6, 13))
    text = all_text(build_compact_digest_blocks(triaged, "weekly", "Jun 06 – Jun 13, 2026"))
    assert "Worth watching" not in text
    assert "5 FYI items" in text
    assert "other" not in text


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
    items = [make_item(1, "urgent"), make_item(2, "inform", impact_score="low")]
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


def test_worth_watching_skips_bills_from_adjourned_sessions():
    items = [
        make_item(1, "inform", source_url="https://openstates.org/ia/bills/2025-2026/SF2225/"),
        make_item(2, "inform", source_url="https://openstates.org/va/bills/2027/HB79/"),
        make_item(3, "inform", source_url="https://openstates.org/pa/bills/2025-2026/HB1705/"),
    ]
    triaged = triage(items, datetime(2026, 10, 29))
    blocks = build_compact_digest_blocks(
        triaged, "weekly", "Oct 26 – Oct 29, 2026", today=datetime(2026, 10, 29)
    )
    text = all_text(blocks)
    assert "Bill number 1 " not in text  # Iowa session adjourned
    assert "Bill number 2 " in text
    assert "Bill number 3 " in text
    # the dead bill still counts toward the FYI total
    assert "1 other FYI item " in text
