"""Unit tests for the digest email template rendering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from digest.builder import EMAIL_TEMPLATE, IMPACT_LABEL


def test_email_template_renders_with_items():
    """Test that the Jinja2 template renders without errors."""

    class FakeItem:
        id = 1
        title = "Colorado Proposes Security Deposit Cap"
        summary = "Colorado SB 100 would cap security deposits at one month's rent."
        impact_score = "high"
        impact_reasoning = "Affects all landlords in Colorado."
        action_needed = "monitor"
        topic_tags = ["security_deposit", "landlord_tenant_law"]
        source_url = "https://example.com/bill"
        effective_date = None
        published_at = None
        discovered_at = None

    html = EMAIL_TEMPLATE.render(
        items=[FakeItem()],
        frequency="weekly",
        date_range="Apr 08 – Apr 15, 2026",
        impact_label=IMPACT_LABEL,
    )

    assert "Colorado Proposes Security Deposit Cap" in html
    assert "TT Policy Tracker" in html
    assert "Weekly Digest" in html
    assert "security deposit" in html


def test_email_template_renders_empty():
    html = EMAIL_TEMPLATE.render(
        items=[],
        frequency="daily",
        date_range="Apr 14 – Apr 15, 2026",
        impact_label=IMPACT_LABEL,
    )
    assert "No new policy items" in html
    assert "Daily Digest" in html
