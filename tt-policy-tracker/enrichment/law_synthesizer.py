"""AI law synthesizer — generates per-(jurisdiction, topic) "current state of law" summaries.

Given the set of PolicyItems we've collected for a specific jurisdiction + topic,
this asks Sonnet to synthesize a narrative of what the law currently looks like,
what's changed recently, and what's pending.

IMPORTANT: This is not a substitute for statutory research. Summaries reflect
only the policy activity we've observed via our feeds. We flag this in the
caveats field of every snapshot.
"""

import json
import logging
from datetime import datetime

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from storage.models import Jurisdiction, LawSnapshot, PolicyItem

logger = logging.getLogger(__name__)

# The 10 canonical topics we track
TOPICS = [
    "landlord_tenant_law",
    "security_deposit",
    "eviction",
    "source_of_income",
    "rental_registration",
    "screening_restrictions",
    "application_fee_limit",
    "rent_control",
    "habitability",
    "fair_housing",
]

TOPIC_LABELS = {
    "landlord_tenant_law": "Landlord-Tenant Law (general)",
    "security_deposit": "Security Deposit Rules",
    "eviction": "Eviction Procedures",
    "source_of_income": "Source-of-Income Discrimination",
    "rental_registration": "Rental Registration / Licensing",
    "screening_restrictions": "Tenant Screening Restrictions",
    "application_fee_limit": "Application Fee Limits",
    "rent_control": "Rent Control / Stabilization",
    "habitability": "Habitability Standards",
    "fair_housing": "Fair Housing",
}


SYNTHESIZER_SYSTEM_PROMPT = """You are a rental housing policy analyst. Given a set of recent policy items (bills, regulations, court rulings) for a specific jurisdiction and topic, synthesize a concise summary of what the current law looks like based on this evidence.

Guidelines:
- Focus on what is currently in effect vs. what is proposed/pending.
- Note conflicting or rapidly changing areas.
- Be honest about gaps — say "based on observed activity, the law appears to..." rather than "the law is..." when uncertain.
- Identify any statutory or regulatory references mentioned in the source items.
- Keep the summary to 3-5 sentences.
- Produce 3-6 key bullet facts.

Respond with ONLY valid JSON (no markdown):
{
  "headline": "One-sentence headline, ≤120 chars",
  "summary": "3-5 sentence narrative describing current state and recent trend",
  "key_facts": ["bullet 1", "bullet 2", "bullet 3"],
  "statutory_references": ["CO Rev Stat § 38-12-103", ...],
  "confidence": "low|med|high",
  "caveats": "1-sentence warning about data limitations, if any"
}

Confidence scale:
- "high" = multiple consistent sources over time, clear direction
- "med" = single strong source OR multiple items but partial information
- "low" = only 1-2 items, or conflicting information, or very narrow coverage"""


async def synthesize_law_snapshot(
    session: AsyncSession,
    jurisdiction_id: int,
    topic: str,
    items: list[PolicyItem],
) -> LawSnapshot | None:
    """Synthesize or update a LawSnapshot for a (jurisdiction, topic) pair."""
    if not items:
        return None

    # Build the prompt context from policy items (newest first)
    items_sorted = sorted(items, key=lambda i: i.discovered_at or datetime.min, reverse=True)

    item_blocks = []
    for idx, item in enumerate(items_sorted[:15], start=1):  # Cap at 15 items to keep prompt size sane
        date_str = item.published_at.strftime("%Y-%m-%d") if item.published_at else "unknown"
        item_blocks.append(
            f"[{idx}] ({date_str}, impact={item.impact_score}) {item.title}\n"
            f"    {item.summary}\n"
            f"    Reasoning: {item.impact_reasoning or '—'}"
        )

    jur = await session.get(Jurisdiction, jurisdiction_id)
    jur_name = jur.name if jur else f"Jurisdiction #{jurisdiction_id}"

    prompt = (
        f"Jurisdiction: {jur_name} ({jur.level if jur else 'unknown'})\n"
        f"Topic: {TOPIC_LABELS.get(topic, topic)}\n"
        f"Number of observed policy items: {len(items)}\n\n"
        f"Source items (most recent first):\n\n"
        + "\n\n".join(item_blocks)
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model=settings.summarizer_model,
            max_tokens=800,
            system=SYNTHESIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)
    except (json.JSONDecodeError, anthropic.APIError) as e:
        logger.error(f"Law synthesizer failed for {jur_name}/{topic}: {e}")
        return None

    valid_confidence = {"low", "med", "high"}
    confidence = result.get("confidence", "med")
    if confidence not in valid_confidence:
        confidence = "med"

    # Check for existing snapshot
    existing_q = select(LawSnapshot).where(
        LawSnapshot.jurisdiction_id == jurisdiction_id,
        LawSnapshot.topic == topic,
    )
    existing = (await session.execute(existing_q)).scalars().first()

    source_item_ids = [item.id for item in items]

    if existing:
        existing.headline = str(result.get("headline", ""))[:200]
        existing.summary = str(result.get("summary", ""))
        existing.key_facts = result.get("key_facts", []) or []
        existing.statutory_references = result.get("statutory_references", []) or []
        existing.source_item_ids = source_item_ids
        existing.confidence = confidence
        existing.caveats = str(result.get("caveats", "")) or None
        snapshot = existing
    else:
        snapshot = LawSnapshot(
            jurisdiction_id=jurisdiction_id,
            topic=topic,
            headline=str(result.get("headline", ""))[:200],
            summary=str(result.get("summary", "")),
            key_facts=result.get("key_facts", []) or [],
            statutory_references=result.get("statutory_references", []) or [],
            source_item_ids=source_item_ids,
            confidence=confidence,
            caveats=str(result.get("caveats", "")) or None,
        )
        session.add(snapshot)

    await session.flush()
    return snapshot


async def find_jurisdiction_topic_pairs_with_items(
    session: AsyncSession,
    min_items: int = 1,
) -> list[tuple[int, str, list[PolicyItem]]]:
    """Find all (jurisdiction_id, topic, items) groups that have at least min_items policy items."""
    # Pull all policy items with jurisdictions
    result = await session.execute(
        select(PolicyItem).where(PolicyItem.jurisdiction_id.is_not(None))
    )
    all_items = result.scalars().all()

    # Group by (jurisdiction_id, topic)
    groups: dict[tuple[int, str], list[PolicyItem]] = {}
    for item in all_items:
        if not item.topic_tags:
            continue
        for topic in item.topic_tags:
            if topic not in TOPICS:
                continue
            key = (item.jurisdiction_id, topic)
            groups.setdefault(key, []).append(item)

    return [
        (jur_id, topic, items)
        for (jur_id, topic), items in groups.items()
        if len(items) >= min_items
    ]
