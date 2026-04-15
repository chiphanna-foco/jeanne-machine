"""Digest builder — queries recent PolicyItems and renders an HTML email."""

import logging
from datetime import datetime, timedelta

from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.models import PolicyItem, Subscription

logger = logging.getLogger(__name__)

IMPACT_EMOJI = {"high": "\U0001f534", "med": "\U0001f7e1", "low": "\U0001f7e2"}
IMPACT_LABEL = {"high": "High Impact", "med": "Medium Impact", "low": "Low Impact"}

EMAIL_TEMPLATE = Template("""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a1a; max-width: 640px; margin: 0 auto; padding: 20px; }
  h1 { color: #1a56db; font-size: 22px; }
  .item { border-left: 4px solid #e5e7eb; padding: 12px 16px; margin-bottom: 16px; background: #f9fafb; border-radius: 0 8px 8px 0; }
  .item.high { border-left-color: #dc2626; }
  .item.med { border-left-color: #f59e0b; }
  .item.low { border-left-color: #10b981; }
  .item h3 { margin: 0 0 6px 0; font-size: 15px; }
  .item h3 a { color: #1a56db; text-decoration: none; }
  .item h3 a:hover { text-decoration: underline; }
  .meta { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
  .summary { font-size: 14px; line-height: 1.5; }
  .impact { font-size: 12px; color: #6b7280; margin-top: 6px; font-style: italic; }
  .topics { margin-top: 6px; }
  .topic-tag { display: inline-block; background: #e0e7ff; color: #3730a3; font-size: 11px; padding: 2px 8px; border-radius: 12px; margin-right: 4px; }
  .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af; }
  .section-header { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; margin: 24px 0 12px 0; }
</style>
</head>
<body>
  <h1>TT Policy Tracker — {{ frequency | title }} Digest</h1>
  <p style="color: #6b7280; font-size: 13px;">{{ date_range }} &middot; {{ items | length }} item{{ 's' if items | length != 1 else '' }}</p>

  {% for score in ['high', 'med', 'low'] %}
  {% set score_items = items | selectattr('impact_score', 'equalto', score) | list %}
  {% if score_items %}
  <div class="section-header">{{ impact_label[score] }} ({{ score_items | length }})</div>
  {% for item in score_items %}
  <div class="item {{ item.impact_score }}">
    <h3><a href="{{ item.source_url or '#' }}">{{ item.title }}</a></h3>
    <div class="meta">
      {% if item.topic_tags %}{{ item.topic_tags | join(', ') | replace('_', ' ') | title }}{% endif %}
      {% if item.action_needed %} &middot; {{ item.action_needed | title }}{% endif %}
    </div>
    <div class="summary">{{ item.summary }}</div>
    {% if item.impact_reasoning %}
    <div class="impact">{{ item.impact_reasoning }}</div>
    {% endif %}
    {% if item.topic_tags %}
    <div class="topics">
      {% for tag in item.topic_tags %}<span class="topic-tag">{{ tag | replace('_', ' ') }}</span>{% endfor %}
    </div>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}
  {% endfor %}

  {% if not items %}
  <p style="color: #6b7280; padding: 20px;">No new policy items this period. We'll keep watching.</p>
  {% endif %}

  <div class="footer">
    <p>TurboTenant Policy Tracker &middot; Internal Tool</p>
    <p>Data sourced from Congress.gov, Open States, Federal Register, and public municipal records.</p>
  </div>
</body>
</html>
""")


async def build_digest(
    session: AsyncSession,
    subscription: Subscription,
) -> tuple[str, list[int]]:
    """Build an HTML digest email for a subscription.

    Returns: (html_content, list_of_item_ids)
    """
    # Determine the lookback window
    if subscription.frequency == "daily":
        lookback = timedelta(days=1)
    else:
        lookback = timedelta(weeks=1)

    since = subscription.last_sent_at or (datetime.utcnow() - lookback)

    # Query matching items
    query = (
        select(PolicyItem)
        .where(PolicyItem.discovered_at >= since)
        .order_by(PolicyItem.impact_score.desc(), PolicyItem.discovered_at.desc())
    )

    # Filter by topics if subscription specifies them
    if subscription.topics:
        query = query.where(PolicyItem.topic_tags.overlap(subscription.topics))

    # Filter by jurisdictions if specified
    if subscription.jurisdictions:
        query = query.where(PolicyItem.jurisdiction_id.in_(subscription.jurisdictions))

    result = await session.execute(query)
    items = result.scalars().all()

    # Determine date range string
    end_date = datetime.utcnow()
    date_range = f"{since.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}"

    html = EMAIL_TEMPLATE.render(
        items=items,
        frequency=subscription.frequency,
        date_range=date_range,
        impact_label=IMPACT_LABEL,
    )

    item_ids = [item.id for item in items]
    return html, item_ids
