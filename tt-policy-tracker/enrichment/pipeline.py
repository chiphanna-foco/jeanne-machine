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
from enrichment.claude_client import EnrichmentAPIError, EnrichmentParseError
from enrichment.classifier import classify_document
from enrichment.geotagger import geotag_from_adapter
from enrichment.keywords import has_housing_subject_tag
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
    adapter = result.scalars().first()
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
    jur = result.scalars().first()
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
    if existing.scalars().first():
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

    Returns the created PolicyItem, or None if the document was classified as
    irrelevant (or already enriched).

    Raises EnrichmentAPIError (doc left unclassified, retried next run) or
    EnrichmentParseError (doc marked classified; caller must commit).
    Callers that loop over a queue should use enrich_counted() instead.
    """
    # Check if already enriched
    existing = await session.execute(
        select(PolicyItem).where(PolicyItem.raw_document_id == raw.id)
    )
    if existing.scalars().first():
        logger.debug(f"Already enriched: raw_document_id={raw.id}")
        return None

    text = raw.raw_text or ""

    # Stage 1: Classify relevance (Haiku — cheap and fast).
    # classified_at is set ONLY after a definitive verdict: a real
    # "irrelevant", or relevant plus a successful summary. An
    # EnrichmentAPIError propagates with classified_at still null, so the
    # next run retries the doc. Unparseable output (after one retry) is the
    # one failure that consumes the doc, so it cannot retry forever.
    try:
        classification = await classify_document(text)
    except EnrichmentParseError:
        raw.classified_at = datetime.utcnow()
        raise

    # Strong curated-subject override: a bill tagged with a housing subject
    # (e.g. LegiScan "Subjects: Housing") is high-precision relevant even when
    # its summary is too thin for the strict classifier — this is what was
    # silently dropping CO HB26-1196 "Tenant Data Information". Trust the tag.
    strong_subject = has_housing_subject_tag(text)
    relevant = classification["relevant"] or strong_subject
    passes_confidence = (
        classification["confidence"] >= settings.relevance_confidence_threshold
        or strong_subject
    )
    if strong_subject and not (
        classification["relevant"]
        and classification["confidence"] >= settings.relevance_confidence_threshold
    ):
        logger.info(f"Housing-subject override → relevant: {raw.external_id}")

    if not (relevant and passes_confidence):
        logger.info(
            f"Irrelevant (conf={classification['confidence']:.2f}): {raw.external_id}"
        )
        raw.classified_at = datetime.utcnow()
        return None

    # Stage 3: Summarize (Sonnet — more expensive, only for relevant docs).
    # Same rule: an API failure leaves the doc retryable.
    try:
        summary = await summarize_document(text)
    except EnrichmentParseError:
        raw.classified_at = datetime.utcnow()
        raise
    raw.classified_at = datetime.utcnow()

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


# Consecutive transient API failures before a run stops calling the API.
# A dead key or a sustained 429 would otherwise burn the whole batch.
MAX_CONSECUTIVE_API_ERRORS = 5
# How many parse-consumed external_ids a run keeps, so they can be healed.
MAX_PARSE_FAILED_IDS = 20


def new_run_counters() -> dict:
    """Counters every enrichment run returns and stores in its run status.

    processed = docs that reached a definitive verdict (relevant + irrelevant).
    """
    return {
        "queued": 0,
        "processed": 0,
        "relevant": 0,
        "irrelevant": 0,
        "api_errors": 0,
        "parse_errors": 0,
        "parse_failed_ids": [],
        "consecutive_api_errors": 0,
        "api_stop_reason": None,
    }


def api_should_stop(counters: dict) -> bool:
    """True when the run should stop calling Claude (retry next run)."""
    return counters.get("api_stop_reason") is not None


async def enrich_counted(
    session: AsyncSession, raw: RawDocument, counters: dict
) -> PolicyItem | None:
    """enrich_document() plus bookkeeping for queue loops.

    Returns the PolicyItem or None. Never raises the two enrichment errors;
    it counts them. The caller commits the session either way: after an API
    error nothing on `raw` changed, after a parse error `classified_at` is set.
    """
    try:
        item = await enrich_document(session, raw)
    except EnrichmentAPIError as e:
        counters["api_errors"] += 1
        counters["consecutive_api_errors"] += 1
        logger.error(f"Claude API error, doc left for retry: {raw.external_id}: {e}")
        if e.definitive:
            counters["api_stop_reason"] = f"{e.kind}: stopped at first failure"
        elif counters["consecutive_api_errors"] >= MAX_CONSECUTIVE_API_ERRORS:
            counters["api_stop_reason"] = (
                f"{e.kind}: {MAX_CONSECUTIVE_API_ERRORS} API errors in a row"
            )
        return None
    except EnrichmentParseError as e:
        counters["parse_errors"] += 1
        counters["consecutive_api_errors"] = 0
        if len(counters["parse_failed_ids"]) < MAX_PARSE_FAILED_IDS:
            counters["parse_failed_ids"].append(raw.external_id)
        logger.error(f"Unparseable model output, doc consumed: {raw.external_id}: {e}")
        return None

    counters["consecutive_api_errors"] = 0
    if raw.classified_at is None:
        # Already had a PolicyItem; nothing was decided this run.
        return item
    counters["processed"] += 1
    if item:
        counters["relevant"] += 1
    else:
        counters["irrelevant"] += 1
    return item
