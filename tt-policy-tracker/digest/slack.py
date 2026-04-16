"""Slack digest sender — posts formatted digest to a Slack webhook.

Uses Slack Block Kit for rich formatting. Requires a Slack Incoming Webhook URL:
https://api.slack.com/messaging/webhooks

Set SLACK_WEBHOOK_URL in env vars to enable.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from storage.models import PolicyItem, Subscription

logger = logging.getLogger(__name__)

IMPACT_EMOJI = {"high": "\U0001f534", "med": "\U0001f7e1", "low": "\U0001f7e2"}
IMPACT_LABEL = {"high": "HIGH IMPACT", "med": "MEDIUM IMPACT", "low": "LOW IMPACT"}
ACTION_EMOJI = {"urgent": "\u26a0\ufe0f", "monitor": "\U0001f441\ufe0f", "inform": "\u2139\ufe0f"}

# Slack limits: max 50 blocks per message, max 3000 chars per text field
MAX_BLOCKS = 50
MAX_TEXT_LENGTH = 2800


def _truncate(text: str, limit: int = MAX_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_topics(topics: list[str] | None) -> str:
    if not topics:
        return ""
    readable = [t.replace("_", " ").title() for t in topics]
    return " · ".join(readable)


def build_slack_blocks(items: list[PolicyItem], frequency: str, date_range: str) -> list[dict]:
    """Build Slack Block Kit blocks for a digest."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"TT Policy Tracker — {frequency.title()} Digest"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_{date_range} · {len(items)} item{'s' if len(items) != 1 else ''}_",
                }
            ],
        },
        {"type": "divider"},
    ]

    if not items:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No new policy items this period. We'll keep watching._",
                },
            }
        )
        return blocks

    # Group by impact score, high first
    by_impact = {"high": [], "med": [], "low": []}
    for item in items:
        by_impact.setdefault(item.impact_score, []).append(item)

    for impact in ("high", "med", "low"):
        group = by_impact.get(impact, [])
        if not group:
            continue

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{IMPACT_EMOJI[impact]} *{IMPACT_LABEL[impact]} ({len(group)})*",
                },
            }
        )

        for item in group:
            if len(blocks) >= MAX_BLOCKS - 2:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"_... and {len(items) - len(blocks)} more items truncated. View full list in the dashboard._",
                        },
                    }
                )
                return blocks

            action_prefix = ""
            if item.action_needed and item.action_needed in ACTION_EMOJI:
                action_prefix = f"{ACTION_EMOJI[item.action_needed]} *{item.action_needed.title()}* · "

            topics_line = _format_topics(item.topic_tags)
            topics_suffix = f"\n_{topics_line}_" if topics_line else ""

            title_text = item.title
            if item.source_url:
                title_text = f"<{item.source_url}|{item.title}>"

            text = (
                f"{action_prefix}*{title_text}*\n"
                f"{_truncate(item.summary, 800)}"
                f"{topics_suffix}"
            )

            if item.impact_reasoning:
                text += f"\n>_{_truncate(item.impact_reasoning, 400)}_"

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": _truncate(text)},
                }
            )

        blocks.append({"type": "divider"})

    return blocks


async def send_to_slack(webhook_url: str, blocks: list[dict], fallback_text: str = "TT Policy Tracker digest") -> bool:
    """POST a message with blocks to a Slack incoming webhook."""
    if not webhook_url:
        logger.warning("No Slack webhook URL configured")
        return False

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            webhook_url,
            json={
                "text": fallback_text,
                "blocks": blocks,
            },
        )
        if resp.status_code == 200 and resp.text == "ok":
            logger.info(f"Slack digest sent ({len(blocks)} blocks)")
            return True
        logger.error(f"Slack webhook failed ({resp.status_code}): {resp.text[:300]}")
        return False


async def build_slack_digest(
    session: AsyncSession,
    subscription: Subscription | None = None,
    lookback: timedelta | None = None,
) -> tuple[list[dict], list[int]]:
    """Build Slack blocks for a digest.

    If subscription is provided, uses its filters and last_sent_at.
    Otherwise defaults to a weekly lookback with no filters.
    """
    if lookback is None:
        lookback = timedelta(weeks=1) if (not subscription or subscription.frequency == "weekly") else timedelta(days=1)

    if subscription and subscription.last_sent_at:
        since = subscription.last_sent_at
    else:
        since = datetime.utcnow() - lookback

    query = (
        select(PolicyItem)
        .where(PolicyItem.discovered_at >= since)
        .order_by(PolicyItem.impact_score.desc(), PolicyItem.discovered_at.desc())
    )

    if subscription:
        if subscription.topics:
            query = query.where(PolicyItem.topic_tags.overlap(subscription.topics))
        if subscription.jurisdictions:
            query = query.where(PolicyItem.jurisdiction_id.in_(subscription.jurisdictions))

    result = await session.execute(query)
    items = list(result.scalars().all())

    end_date = datetime.utcnow()
    date_range = f"{since.strftime('%b %d')} \u2013 {end_date.strftime('%b %d, %Y')}"
    frequency = subscription.frequency if subscription else "weekly"

    blocks = build_slack_blocks(items, frequency, date_range)
    item_ids = [item.id for item in items]

    return blocks, item_ids
