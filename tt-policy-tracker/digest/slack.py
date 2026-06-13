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
from storage.models import ItemFeedback, PolicyItem, Subscription

logger = logging.getLogger(__name__)

IMPACT_EMOJI = {"high": "\U0001f534", "med": "\U0001f7e1", "low": "\U0001f7e2"}
ACTION_EMOJI = {"urgent": "\u26a0\ufe0f", "monitor": "\U0001f441\ufe0f", "inform": "\u2139\ufe0f"}

# Slack limits: max 50 blocks per message, max 3000 chars per text field
MAX_BLOCKS = 50
MAX_TEXT_LENGTH = 2800

# Compact digest caps \u2014 a national-search backfill week can produce 100+
# items; the digest lists at most this many lines per bucket and points to
# the dashboard for the rest. FYI items are never listed, only counted.
DIGEST_ACT_NOW_LINES = 15
DIGEST_MONITOR_LINES = 10
DASHBOARD_URL = "https://jeanne-machine.vercel.app"


def _truncate(text: str, limit: int = MAX_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _bill_tag(bill_key: str | None) -> str:
    """'CO:HB1045:2026' → 'CO HB1045' — a compact line prefix."""
    if not bill_key:
        return ""
    parts = bill_key.split(":")
    if len(parts) >= 2 and len(parts[0]) == 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def _digest_line(item: dict) -> str:
    """One line per bill: action emoji, state+bill tag, linked title, effective date."""
    emoji = ACTION_EMOJI.get(item.get("action_needed"), "•")
    tag = _bill_tag(item.get("bill_key"))
    title = _truncate(item.get("title") or "", 120)
    if item.get("source_url"):
        title = f"<{item['source_url']}|{title}>"
    eff = item.get("effective_date")
    eff_part = f" — effective {str(eff)[:10]}" if eff else ""
    prefix = f"*{tag}* · " if tag else ""
    return f"{emoji} {prefix}{title}{eff_part}"


def _lines_to_sections(lines: list[str]) -> list[dict]:
    """Pack one-liners into as few section blocks as the 3000-char limit allows."""
    blocks: list[dict] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        if buf and size + len(line) + 1 > MAX_TEXT_LENGTH:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(buf)}})
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(buf)}})
    return blocks


def build_compact_digest_blocks(
    triaged: dict,
    frequency: str,
    date_range: str,
    suppressed: int = 0,
    dashboard_url: str = DASHBOARD_URL,
) -> list[dict]:
    """Compact digest: one line per bill, act-now first, FYI as a count only.

    `triaged` is enrichment.triage.triage() output:
    {act_now, monitor, fyi, counts, deduped_removed}. Summaries and impact
    reasoning live in the dashboard, not the digest — a backfill week with
    100+ items must still read as a skimmable recap, not a wall of text.
    """
    counts = triaged.get("counts", {})
    act_now = triaged.get("act_now", [])
    monitor = triaged.get("monitor", [])
    fyi_count = counts.get("fyi", len(triaged.get("fyi", [])))
    total = len(act_now) + len(monitor) + fyi_count

    meta_bits = [date_range, f"{total} item{'s' if total != 1 else ''}"]
    removed = triaged.get("deduped_removed", 0)
    if removed:
        meta_bits.append(f"{removed} duplicate{'s' if removed != 1 else ''} collapsed")
    if suppressed:
        meta_bits.append(f"{suppressed} dismissed hidden")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"TT Policy Tracker — {frequency.title()} Digest"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{' · '.join(meta_bits)}_"}],
        },
        {"type": "divider"},
    ]

    if total == 0:
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

    for label, items, cap in (
        ("⚠️ Act now", act_now, DIGEST_ACT_NOW_LINES),
        ("👁️ Monitor", monitor, DIGEST_MONITOR_LINES),
    ):
        if not items:
            continue
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{label} ({len(items)})*"},
            }
        )
        blocks.extend(_lines_to_sections([_digest_line(it) for it in items[:cap]]))
        overflow = len(items) - cap
        if overflow > 0:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_… and {overflow} more — <{dashboard_url}|see all in the dashboard>_",
                        }
                    ],
                }
            )
        blocks.append({"type": "divider"})

    footer_bits = []
    if fyi_count:
        footer_bits.append(f"ℹ️ {fyi_count} FYI item{'s' if fyi_count != 1 else ''} (early-stage / dead / niche) tracked but not listed")
    footer_bits.append(f"<{dashboard_url}|dashboard>")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " · ".join(footer_bits)}],
        }
    )
    return blocks


def build_alert_blocks(
    items: list[dict],
    tracked_count: int = 0,
    dashboard_url: str = "https://jeanne-machine.vercel.app",
) -> list[dict]:
    """Compact act-now alert: one line per law, built for a busy legal team.

    `items` are alert-gated dicts (see enrichment.alerting) with keys:
    title, source_url, impact_score, effective_date, impact_reasoning.
    `tracked_count` = items ingested this run but NOT alerted (watchlist) —
    surfaced as a one-line footer so nothing feels hidden.
    """
    n = len(items)
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"⚖️ *{n} law update{'s' if n != 1 else ''} needing attention*",
            },
        }
    ]

    lines = []
    for it in items:
        emoji = IMPACT_EMOJI.get(it.get("impact_score"), "•")
        title = _truncate(it.get("title") or "", 150)
        if it.get("source_url"):
            title = f"<{it['source_url']}|{title}>"
        eff = it.get("effective_date")
        eff_part = f" — effective {str(eff)[:10]}" if eff else ""
        line = f"{emoji} {title}{eff_part}"
        why = (it.get("impact_reasoning") or "").strip()
        if why:
            line += f"\n        _{_truncate(why, 160)}_"
        lines.append(line)
    if lines:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": _truncate("\n".join(lines))}}
        )

    footer_bits = []
    if tracked_count:
        footer_bits.append(f"{tracked_count} more tracked on the watchlist (not urgent)")
    footer_bits.append(f"<{dashboard_url}|dashboard>")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " · ".join(footer_bits)}],
        }
    )
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


def _item_dict(item: PolicyItem) -> dict:
    """PolicyItem → plain dict for the pure triage/feedback helpers."""
    return {
        "id": item.id,
        "title": item.title,
        "impact_score": item.impact_score,
        "action_needed": item.action_needed,
        "source_url": item.source_url,
        "effective_date": item.effective_date.isoformat() if item.effective_date else None,
        "discovered_at": item.discovered_at.isoformat() if item.discovered_at else None,
    }


async def _latest_feedback_map(session: AsyncSession) -> dict[str, str]:
    """{bill_key: latest_label} from the append-only item_feedback log."""
    rows = (
        await session.execute(
            select(ItemFeedback.bill_key, ItemFeedback.label).order_by(
                ItemFeedback.created_at.asc()
            )
        )
    ).all()
    return {bill_key: label for bill_key, label in rows}


async def build_slack_digest(
    session: AsyncSession,
    subscription: Subscription | None = None,
    lookback: timedelta | None = None,
) -> tuple[list[dict], list[int]]:
    """Build compact Slack blocks for a digest.

    If subscription is provided, uses its filters and last_sent_at.
    Otherwise defaults to a weekly lookback with no filters.

    Items go through the same pipeline as the dashboard triage view —
    cross-source dedup, 👎-feedback suppression, act-now/monitor/fyi
    bucketing — then render one line per bill (build_compact_digest_blocks),
    so a heavy ingest week doesn't blast a wall of summaries into Slack.
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

    from enrichment.feedback import annotate_and_suppress
    from enrichment.triage import triage

    dicts = [_item_dict(it) for it in items]
    fb = await _latest_feedback_map(session)
    visible = annotate_and_suppress(dicts, fb)
    suppressed = len(dicts) - len(visible)
    triaged = triage(visible, datetime.utcnow())

    end_date = datetime.utcnow()
    date_range = f"{since.strftime('%b %d')} \u2013 {end_date.strftime('%b %d, %Y')}"
    frequency = subscription.frequency if subscription else "weekly"

    blocks = build_compact_digest_blocks(triaged, frequency, date_range, suppressed=suppressed)
    item_ids = [
        it["id"]
        for bucket in ("act_now", "monitor", "fyi")
        for it in triaged.get(bucket, [])
    ]

    return blocks, item_ids
