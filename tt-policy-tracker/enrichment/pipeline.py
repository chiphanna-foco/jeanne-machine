"""End-to-end enrichment pipeline: classify → summarize → geotag → store.

Orchestrates the enrichment stages for a batch of raw documents.
"""

import hashlib
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.base import RawDoc
from config import settings
from enrichment.classifier import classify_document
from enrichment.geotagger import geotag_from_adapter
from enrichment.summarizer import summarize_document
from storage.models import (
    Jurisdiction,
    PolicyItem,
    RawDocument,
    SourceAdapter,
)

logger = logging.getLogger(__name__)


async def ensure_source_adapter(session: AsyncSession, name: str) -> int:
    """Get or create a SourceAdapter row, return its id."""
    result = await session.execute(select(SourceAdapter).where(SourceAdapter.name == name))
    adapter = result.scalar_one_or_none()
    if adapter:
        return adapter.id

    adapter = SourceAdapter(name=name, enabled=True)
    session.add(adapter)
    await session.flush()
    return adapter.id


async def ensure_jurisdiction(
    session: AsyncSession, name: str, level: str, state_code: str | None
) -> int:
    """Get or create a Jurisdiction row, return its id."""
    query = select(Jurisdiction).where(
        Jurisdiction.name == name, Jurisdiction.level == level
    )
    result = await session.execute(query)
    jur = result.scalar_one_or_none()
    if jur:
        return jur.id

    jur = Jurisdiction(name=name, level=level, state_code=state_code)
    session.add(jur)
    await session.flush()
    return jur.id


async def ingest_raw_doc(session: AsyncSession, doc: RawDoc) -> RawDocument | None:
    """Store a RawDoc in the database. Returns None if already exists (dedup by content_hash)."""
    content_hash = hashlib.sha256(doc.raw_text.encode()).hexdigest()

    # Check for duplicate
    existing = await session.execute(
        select(RawDocument).where(RawDocument.content_hash == content_hash)
    )
    if existing.scalar_one_or_none():
        logger.debug(f"Skipping duplicate: {doc.external_id}")
        return None

    source_id = await ensure_source_adapter(session, doc.source_name)
    geo = geotag_from_adapter(doc.jurisdiction_name, doc.jurisdiction_level, doc.state_code)
    jur_id = await ensure_jurisdiction(
        session, geo["jurisdiction_name"], geo["level"], geo["state_code"]
    )

    raw = RawDocument(
        source_adapter_id=source_id,
        jurisdiction_id=jur_id,
        external_id=doc.external_id,
        url=doc.url,
        raw_text=doc.raw_text,
        content_hash=content_hash,
        fetched_at=datetime.utcnow(),
    )
    session.add(raw)
    await session.flush()
    return raw


async def enrich_document(session: AsyncSession, raw: RawDocument) -> PolicyItem | None:
    """Run the full enrichment pipeline on a single RawDocument.

    Returns the created PolicyItem, or None if the document was classified as irrelevant.
    """
    # Check if already enriched
    existing = await session.execute(
        select(PolicyItem).where(PolicyItem.raw_document_id == raw.id)
    )
    if existing.scalar_one_or_none():
        logger.debug(f"Already enriched: raw_document_id={raw.id}")
        return None

    text = raw.raw_text or ""

    # Stage 1: Classify relevance (Haiku — cheap and fast)
    classification = await classify_document(text)
    if not classification["relevant"] or classification["confidence"] < settings.relevance_confidence_threshold:
        logger.info(
            f"Irrelevant (conf={classification['confidence']:.2f}): {raw.external_id}"
        )
        return None

    # Stage 3: Summarize (Sonnet — more expensive, only for relevant docs)
    try:
        summary = await summarize_document(text)
    except Exception as e:
        logger.error(f"Summarization failed for {raw.external_id}: {e}")
        return None

    # Parse effective date
    effective_date = None
    if summary.get("effective_date"):
        try:
            effective_date = datetime.strptime(summary["effective_date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # Create PolicyItem
    item = PolicyItem(
        raw_document_id=raw.id,
        jurisdiction_id=raw.jurisdiction_id,
        title=summary["title"],
        summary=summary["summary"],
        full_text=text,
        impact_score=summary["impact_score"],
        impact_reasoning=summary.get("impact_reasoning"),
        action_needed=summary.get("action_needed"),
        effective_date=effective_date,
        published_at=raw.fetched_at,
        source_url=raw.url,
        topic_tags=summary.get("topics", []) or classification.get("topics", []),
    )
    session.add(item)
    await session.flush()

    logger.info(
        f"Enriched: {item.title} (impact={item.impact_score}, topics={item.topic_tags})"
    )
    return item
