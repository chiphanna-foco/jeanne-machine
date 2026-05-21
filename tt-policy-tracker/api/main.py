"""FastAPI internal API for the TT Policy Tracker."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from storage.database import async_session, get_session
from storage.models import Base, Jurisdiction, LawSnapshot, PolicyItem, RawDocument, Subscription

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations / table creation on startup."""
    try:
        sync_engine = create_engine(settings.sync_database_url)
        with sync_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(sync_engine)
        # Idempotent column-level migrations for changes Base.metadata.create_all
        # won't apply to existing tables.
        with sync_engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE raw_document "
                "ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ"
            ))
            # Backfill: any raw_document that already has a policy_item was
            # successfully classified at some point. Mark it so we don't re-
            # classify it. Rejected docs we never tracked will get one final
            # re-classification pass (and then be permanently marked).
            conn.execute(text(
                "UPDATE raw_document "
                "SET classified_at = COALESCE(classified_at, CURRENT_TIMESTAMP) "
                "WHERE id IN (SELECT raw_document_id FROM policy_item) "
                "AND classified_at IS NULL"
            ))
            conn.commit()
        sync_engine.dispose()
        logger.info("Database tables ready")
    except Exception as e:
        logger.warning(f"Auto-migration on startup failed (ok if tables exist): {e}")
    yield


app = FastAPI(
    title="TT Policy Tracker API",
    description="Internal API for the TurboTenant Legislative Policy Tracker",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "service": "jeanne-machine"}


@app.get("/")
async def root():
    return {
        "service": "Jeanne Machine API",
        "status": "ok",
        "dashboard": "https://jeanne-machine.vercel.app",
        "docs": "/docs",
    }


# ── Auth verification ──────────────────────────────────────────────


@app.get("/api/auth/verify")
async def verify_auth(token: str | None = None):
    """Verify a password/token matches ADMIN_TOKEN.

    If no ADMIN_TOKEN is configured on the server, anything passes (dev mode).
    Returns: {"valid": true/false, "auth_required": true/false}
    """
    if not settings.admin_token:
        return {"valid": True, "auth_required": False}
    return {"valid": token == settings.admin_token, "auth_required": True}


# ── Policy Items ────────────────────────────────────────────────────


@app.get("/api/items")
async def list_items(
    topic: str | None = None,
    impact: str | None = None,
    jurisdiction_id: int | None = None,
    state: str | None = None,
    since: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List policy items with optional filters."""
    query = select(PolicyItem).order_by(PolicyItem.discovered_at.desc())

    if topic:
        query = query.where(PolicyItem.topic_tags.contains([topic]))
    if impact:
        query = query.where(PolicyItem.impact_score == impact)
    if jurisdiction_id:
        query = query.where(PolicyItem.jurisdiction_id == jurisdiction_id)
    if state:
        query = query.join(Jurisdiction).where(Jurisdiction.state_code == state.upper())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(PolicyItem.discovered_at >= since_dt)
        except ValueError:
            pass

    total_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(total_q)).scalar() or 0

    result = await session.execute(query.offset(offset).limit(limit))
    items = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "summary": item.summary,
                "impact_score": item.impact_score,
                "impact_reasoning": item.impact_reasoning,
                "action_needed": item.action_needed,
                "topics": item.topic_tags,
                "source_url": item.source_url,
                "effective_date": item.effective_date.isoformat() if item.effective_date else None,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "discovered_at": item.discovered_at.isoformat() if item.discovered_at else None,
                "jurisdiction_id": item.jurisdiction_id,
            }
            for item in items
        ],
    }


@app.get("/api/items/{item_id}")
async def get_item(item_id: int, session: AsyncSession = Depends(get_session)):
    """Get a single policy item by ID."""
    result = await session.execute(select(PolicyItem).where(PolicyItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "not found"}, 404

    return {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "full_text": item.full_text,
        "impact_score": item.impact_score,
        "impact_reasoning": item.impact_reasoning,
        "action_needed": item.action_needed,
        "topics": item.topic_tags,
        "source_url": item.source_url,
        "effective_date": item.effective_date.isoformat() if item.effective_date else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "discovered_at": item.discovered_at.isoformat() if item.discovered_at else None,
        "jurisdiction_id": item.jurisdiction_id,
    }


# ── Jurisdictions ───────────────────────────────────────────────────


@app.get("/api/jurisdictions")
async def list_jurisdictions(
    level: str | None = None,
    state: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """List jurisdictions."""
    query = select(Jurisdiction).order_by(Jurisdiction.level, Jurisdiction.name)
    if level:
        query = query.where(Jurisdiction.level == level)
    if state:
        query = query.where(Jurisdiction.state_code == state.upper())

    result = await session.execute(query)
    jurisdictions = result.scalars().all()

    return {
        "jurisdictions": [
            {
                "id": j.id,
                "name": j.name,
                "level": j.level,
                "state_code": j.state_code,
            }
            for j in jurisdictions
        ]
    }


# ── Subscriptions ──────────────────────────────────────────────────


@app.get("/api/subscriptions")
async def list_subscriptions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Subscription).where(Subscription.active.is_(True)))
    subs = result.scalars().all()
    return {
        "subscriptions": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "email": s.email,
                "frequency": s.frequency,
                "topics": s.topics,
                "jurisdictions": s.jurisdictions,
                "active": s.active,
                "last_sent_at": s.last_sent_at.isoformat() if s.last_sent_at else None,
            }
            for s in subs
        ]
    }


@app.post("/api/subscriptions")
async def create_subscription(
    user_id: str,
    email: str,
    frequency: str = "weekly",
    topics: list[str] | None = None,
    jurisdiction_ids: list[int] | None = None,
    session: AsyncSession = Depends(get_session),
):
    sub = Subscription(
        user_id=user_id,
        email=email,
        frequency=frequency,
        topics=topics,
        jurisdictions=jurisdiction_ids,
        active=True,
    )
    session.add(sub)
    await session.commit()
    return {"id": sub.id, "status": "created"}


# ── Stats ──────────────────────────────────────────────────────────


@app.get("/api/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Dashboard stats."""
    total_items = (await session.execute(select(func.count(PolicyItem.id)))).scalar() or 0
    high_impact = (
        await session.execute(
            select(func.count(PolicyItem.id)).where(PolicyItem.impact_score == "high")
        )
    ).scalar() or 0
    total_jurisdictions = (
        await session.execute(select(func.count(Jurisdiction.id)))
    ).scalar() or 0

    return {
        "total_items": total_items,
        "high_impact_items": high_impact,
        "total_jurisdictions": total_jurisdictions,
    }


# ── Admin: Pipeline Triggers ──────────────────────────────────────


def _check_admin_token(token: str | None) -> bool:
    """Verify admin token. If no token is configured, allow access (dev mode)."""
    if not settings.admin_token:
        return True
    return token == settings.admin_token


@app.get("/admin/run-pipeline")
async def run_pipeline(
    days_back: int = Query(default=30, le=730),
    batch_size: int = Query(default=50, le=200),
    state: list[str] = Query(default=[]),
    token: str | None = Query(default=None),
):
    """Trigger ingestion + enrichment in one call.

    Usage:
      /admin/run-pipeline?days_back=30&batch_size=50&token=YOUR_TOKEN

    Optional `state` (repeatable): restrict OpenStates ingest to these
    two-letter state codes only and skip the other adapters. Useful for
    targeted backfill without waiting on a full 50-state run.
      /admin/run-pipeline?days_back=365&state=wa&state=ca&token=...
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    states_filter = [s.lower() for s in state] if state else None
    asyncio.create_task(_run_pipeline_task(days_back, batch_size, states_filter))

    return {
        "status": "started",
        "message": (
            f"Pipeline started: ingesting {days_back} days back"
            + (f" (states={states_filter})" if states_filter else "")
            + f", then enriching up to {batch_size} docs. Check /admin/pipeline-status for progress."
        ),
    }


# Simple in-memory status tracking
_pipeline_status = {"running": False, "last_run": None, "last_result": None}


@app.get("/admin/pipeline-status")
async def pipeline_status(token: str | None = Query(default=None)):
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})
    return _pipeline_status


async def _run_pipeline_task(
    days_back: int,
    batch_size: int,
    states_filter: list[str] | None = None,
):
    """Background task: ingest from all adapters, then enrich."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"ingested": 0, "enriched": 0, "irrelevant": 0, "errors": []}
    new_item_ids: list[int] = []

    try:
        # ── Step 1: Ingest ──
        from adapters.congress import CongressAdapter
        from adapters.courtlistener import CourtListenerAdapter
        from adapters.federal_register import FederalRegisterAdapter
        from adapters.legistar import LegistarAdapter
        from adapters.openstates import ALL_STATES, OpenStatesAdapter
        from adapters.wa_leg import WaLegAdapter
        from enrichment.pipeline import enrich_document, ingest_raw_doc

        since = datetime.utcnow() - timedelta(days=days_back)
        if states_filter:
            states_lower = [s.lower() for s in states_filter]
            adapters = []
            # Direct state adapters first — they don't share rate budgets
            # with Open States and may succeed when OS is throttled.
            if "wa" in states_lower:
                adapters.append(WaLegAdapter())
            adapters.append(OpenStatesAdapter(states=states_filter))
        else:
            os_states = ALL_STATES if settings.openstates_scope == "all" else None
            adapters = [
                OpenStatesAdapter(states=os_states),
                WaLegAdapter(),
                CongressAdapter(),
                FederalRegisterAdapter(),
                LegistarAdapter(),
            ]
            if settings.courtlistener_api_token:
                adapters.append(CourtListenerAdapter())

        for adapter in adapters:
            try:
                docs = await adapter.fetch_new_items(since)
                logger.info(f"{adapter.source_name}: fetched {len(docs)} docs")
                async with async_session() as session:
                    for doc in docs:
                        raw = await ingest_raw_doc(session, doc)
                        if raw:
                            results["ingested"] += 1
                    await session.commit()
                # Surface per-state stats if the adapter exposes them
                per_state = getattr(adapter, "last_run_stats", None)
                if per_state:
                    key = f"{adapter.source_name}_by_state"
                    results[key] = per_state
                    for st, info in per_state.items():
                        if info.get("error"):
                            results["errors"].append(
                                f"{adapter.source_name} {st}: {info['error']}"
                            )
            except Exception as e:
                err = f"{adapter.source_name}: {str(e)}"
                logger.error(err, exc_info=True)
                results["errors"].append(err)

        # ── Step 2: Enrich ──
        # First fetch the list of raw docs to process (in its own session)
        async with async_session() as session:
            query = (
                select(RawDocument.id)
                .where(RawDocument.classified_at.is_(None))
                .order_by(RawDocument.fetched_at.desc())
                .limit(batch_size)
            )
            result = await session.execute(query)
            raw_ids = list(result.scalars().all())

        # Then enrich each doc in its own session — one failure won't kill the batch
        for raw_id in raw_ids:
            try:
                async with async_session() as session:
                    raw = await session.get(RawDocument, raw_id)
                    if not raw:
                        continue
                    item = await enrich_document(session, raw)
                    if item:
                        results["enriched"] += 1
                        new_item_ids.append(item.id)
                    else:
                        results["irrelevant"] += 1
                    await session.commit()
            except Exception as e:
                err = f"enrich raw_id={raw_id}: {type(e).__name__}: {str(e)[:300]}"
                logger.error(err)
                results["errors"].append(err)

        # ── Step 3: Slack push if any new items ──
        if new_item_ids and settings.slack_webhook_url:
            try:
                from digest.slack import build_slack_blocks, send_to_slack

                async with async_session() as session:
                    rows = await session.execute(
                        select(PolicyItem)
                        .where(PolicyItem.id.in_(new_item_ids))
                        .order_by(
                            PolicyItem.impact_score.desc(),
                            PolicyItem.discovered_at.desc(),
                        )
                    )
                    items = list(rows.scalars().all())

                date_range = datetime.utcnow().strftime("%b %d, %Y")
                blocks = build_slack_blocks(items, frequency="search", date_range=date_range)
                fallback = (
                    f"TT Policy Tracker — {len(items)} new item"
                    f"{'s' if len(items) != 1 else ''}"
                )
                ok = await send_to_slack(settings.slack_webhook_url, blocks, fallback_text=fallback)
                results["slack_sent"] = ok
                results["slack_item_count"] = len(items)
                if not ok:
                    results["errors"].append("Slack webhook send failed")
            except Exception as e:
                results["errors"].append(f"slack stage: {type(e).__name__}: {str(e)[:300]}")
                logger.error(f"Slack push from pipeline failed: {e}", exc_info=True)

    except Exception as e:
        results["errors"].append(f"pipeline error: {str(e)}")
        logger.error(f"Pipeline failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


@app.get("/admin/run-enrich")
async def run_enrich_only(
    batch_size: int = Query(default=200, le=500),
    min_confidence: float = Query(default=0.5),
    source: str | None = Query(default=None),
    state: str | None = Query(default=None),
    token: str | None = Query(default=None),
):
    """Run enrichment only (no ingestion). Optionally filter the queue.

    Usage:
      /admin/run-enrich?batch_size=200&token=YOUR_TOKEN
      /admin/run-enrich?source=openstates&state=wa&batch_size=200&token=...

    Filters (both optional):
      - source: adapter name (openstates, congress, federal_register,
        legistar, courtlistener)
      - state: two-letter state code (filters raw docs by their
        jurisdiction's state_code)
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_enrich_task(batch_size, min_confidence, source, state))

    return {
        "status": "started",
        "message": (
            f"Enrichment started: batch_size={batch_size}, "
            f"min_confidence={min_confidence}"
            + (f", source={source}" if source else "")
            + (f", state={state.upper()}" if state else "")
            + ". Check /admin/pipeline-status for progress."
        ),
    }


async def _run_enrich_task(
    batch_size: int,
    min_confidence: float,
    source: str | None = None,
    state: str | None = None,
):
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"enriched": 0, "irrelevant": 0, "errors": []}

    try:
        from enrichment.classifier import classify_document
        from enrichment.summarizer import summarize_document
        from storage.models import SourceAdapter

        # Temporarily override the confidence threshold
        original_threshold = settings.relevance_confidence_threshold
        settings.relevance_confidence_threshold = min_confidence

        async with async_session() as session:
            query = select(RawDocument.id).where(RawDocument.classified_at.is_(None))
            if source:
                query = query.join(
                    SourceAdapter, RawDocument.source_adapter_id == SourceAdapter.id
                ).where(SourceAdapter.name == source)
            if state:
                query = query.join(
                    Jurisdiction, RawDocument.jurisdiction_id == Jurisdiction.id
                ).where(Jurisdiction.state_code == state.upper())
            query = query.order_by(RawDocument.fetched_at.desc()).limit(batch_size)
            result = await session.execute(query)
            raw_ids = list(result.scalars().all())

        logger.info(f"Enrich-only: {len(raw_ids)} docs to process")

        from enrichment.pipeline import enrich_document

        for raw_id in raw_ids:
            try:
                async with async_session() as session:
                    raw = await session.get(RawDocument, raw_id)
                    if not raw:
                        continue
                    item = await enrich_document(session, raw)
                    if item:
                        results["enriched"] += 1
                    else:
                        results["irrelevant"] += 1
                    await session.commit()
            except Exception as e:
                results["errors"].append(f"enrich raw_id={raw_id}: {type(e).__name__}: {str(e)[:300]}")

        settings.relevance_confidence_threshold = original_threshold

    except Exception as e:
        results["errors"].append(f"enrich error: {str(e)}")

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


@app.get("/admin/drain-enrich")
async def drain_enrich(
    source: str | None = Query(default=None),
    state: str | None = Query(default=None),
    batch_size: int = Query(default=500, le=500),
    max_batches: int = Query(default=30, le=100),
    min_confidence: float = Query(default=0.5),
    token: str | None = Query(default=None),
):
    """Run repeated enrichment batches until the queue is empty (or max_batches hit).

    One curl, walks away, comes back. Internally loops `/admin/run-enrich`
    semantics until a batch returns zero docs. Useful for backfilling a
    specific source/state without hand-curling the same call 10+ times.

    Usage:
      /admin/drain-enrich?source=wa_leg&state=WA&token=YOUR_TOKEN

    Filters match /admin/run-enrich. Status is reported via
    /admin/pipeline-status — `last_result.batches_run`, `total_enriched`,
    `total_irrelevant`.
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(
        _run_drain_task(source, state, batch_size, max_batches, min_confidence)
    )
    return {
        "status": "started",
        "message": (
            f"Drain started: source={source}, state={state}, "
            f"batch_size={batch_size}, max_batches={max_batches}. "
            "Check /admin/pipeline-status for progress."
        ),
    }


async def _run_drain_task(
    source: str | None,
    state: str | None,
    batch_size: int,
    max_batches: int,
    min_confidence: float,
):
    global _pipeline_status
    _pipeline_status = {
        "running": True,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": None,
    }

    totals = {
        "batches_run": 0,
        "total_enriched": 0,
        "total_irrelevant": 0,
        "errors": [],
        "stopped_reason": None,
    }

    try:
        from enrichment.pipeline import enrich_document
        from storage.models import SourceAdapter

        original_threshold = settings.relevance_confidence_threshold
        settings.relevance_confidence_threshold = min_confidence

        for batch_num in range(1, max_batches + 1):
            async with async_session() as session:
                query = select(RawDocument.id).where(RawDocument.classified_at.is_(None))
                if source:
                    query = query.join(
                        SourceAdapter, RawDocument.source_adapter_id == SourceAdapter.id
                    ).where(SourceAdapter.name == source)
                if state:
                    query = query.join(
                        Jurisdiction, RawDocument.jurisdiction_id == Jurisdiction.id
                    ).where(Jurisdiction.state_code == state.upper())
                query = query.order_by(RawDocument.fetched_at.desc()).limit(batch_size)
                result = await session.execute(query)
                raw_ids = list(result.scalars().all())

            if not raw_ids:
                totals["stopped_reason"] = "queue empty"
                break

            batch_enriched = 0
            batch_irrelevant = 0
            for raw_id in raw_ids:
                try:
                    async with async_session() as session:
                        raw = await session.get(RawDocument, raw_id)
                        if not raw:
                            continue
                        item = await enrich_document(session, raw)
                        if item:
                            batch_enriched += 1
                        else:
                            batch_irrelevant += 1
                        await session.commit()
                except Exception as e:
                    totals["errors"].append(
                        f"batch {batch_num} raw_id={raw_id}: {type(e).__name__}: {str(e)[:200]}"
                    )

            totals["batches_run"] = batch_num
            totals["total_enriched"] += batch_enriched
            totals["total_irrelevant"] += batch_irrelevant
            logger.info(
                f"drain batch {batch_num}: enriched={batch_enriched}, "
                f"irrelevant={batch_irrelevant}"
            )
            # Reflect progress between batches so polling shows live counts
            _pipeline_status["last_result"] = dict(totals)

        if totals["stopped_reason"] is None:
            totals["stopped_reason"] = f"max_batches={max_batches} reached"

        settings.relevance_confidence_threshold = original_threshold

    except Exception as e:
        totals["errors"].append(f"drain error: {type(e).__name__}: {str(e)[:300]}")
        logger.error(f"Drain failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": totals,
    }

    # Slack ping so the user doesn't have to poll pipeline-status
    if settings.slack_webhook_url:
        try:
            from digest.slack import send_to_slack

            filters = []
            if source:
                filters.append(f"source={source}")
            if state:
                filters.append(f"state={state.upper()}")
            filter_str = " ".join(filters) if filters else "no filters"
            err_str = f", {len(totals['errors'])} errors" if totals["errors"] else ""
            text = (
                f"*Drain done* ({filter_str}): "
                f"{totals['total_enriched']} enriched, "
                f"{totals['total_irrelevant']} irrelevant, "
                f"{totals['batches_run']} batches{err_str}. "
                f"Stopped: {totals['stopped_reason']}."
            )
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
            await send_to_slack(settings.slack_webhook_url, blocks, fallback_text=text)
        except Exception as e:
            logger.error(f"Slack notify after drain failed: {e}")


@app.get("/admin/db-stats")
async def db_stats(
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Show detailed database counts for debugging."""
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    total_raw = (await session.execute(select(func.count(RawDocument.id)))).scalar() or 0
    total_enriched = (await session.execute(select(func.count(PolicyItem.id)))).scalar() or 0

    # Count un-classified (raw docs the classifier hasn't seen yet)
    unenriched = (await session.execute(
        select(func.count(RawDocument.id)).where(RawDocument.classified_at.is_(None))
    )).scalar() or 0

    # Sample some raw doc titles to see what we're getting
    sample_q = select(RawDocument.external_id, RawDocument.raw_text).order_by(RawDocument.fetched_at.desc()).limit(5)
    sample_result = await session.execute(sample_q)
    samples = [
        {"external_id": r[0], "preview": (r[1] or "")[:200]}
        for r in sample_result.all()
    ]

    return {
        "total_raw_documents": total_raw,
        "total_enriched_items": total_enriched,
        "unenriched_remaining": unenriched,
        "recent_raw_samples": samples,
    }


@app.get("/admin/stats-by-state")
async def stats_by_state(
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Per-state document counts (raw + enriched) so we can see coverage at a glance.

    Usage: /admin/stats-by-state?token=YOUR_TOKEN
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    raw_q = (
        select(Jurisdiction.state_code, func.count(RawDocument.id))
        .join(RawDocument, RawDocument.jurisdiction_id == Jurisdiction.id)
        .where(Jurisdiction.state_code.isnot(None))
        .group_by(Jurisdiction.state_code)
    )
    raw_counts = {row[0]: row[1] for row in (await session.execute(raw_q)).all()}

    enriched_q = (
        select(Jurisdiction.state_code, func.count(PolicyItem.id))
        .join(PolicyItem, PolicyItem.jurisdiction_id == Jurisdiction.id)
        .where(Jurisdiction.state_code.isnot(None))
        .group_by(Jurisdiction.state_code)
    )
    enriched_counts = {row[0]: row[1] for row in (await session.execute(enriched_q)).all()}

    states = sorted(set(raw_counts) | set(enriched_counts))
    rows = [
        {
            "state": s,
            "raw": raw_counts.get(s, 0),
            "enriched": enriched_counts.get(s, 0),
        }
        for s in states
    ]
    rows.sort(key=lambda r: r["raw"], reverse=True)
    return {"states": rows}


@app.get("/admin/wsl-probe")
async def wsl_probe(
    biennium: str = Query(default="2025-26"),
    bill_number: str = Query(default="1217"),
    topical_index: str = Query(default="Housing"),
    token: str | None = Query(default=None),
):
    """Probe WSL Web Services to figure out which call pattern works.

    wa_leg is currently 500'ing on every request — this hits multiple
    endpoint/parameter variants and returns the raw status + response
    snippet for each so we can see exactly what WSL accepts.

    Usage:
      /admin/wsl-probe?token=YOUR_TOKEN
      /admin/wsl-probe?biennium=2025-26&bill_number=1217&topical_index=Housing&token=...
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    import httpx

    base = "https://wslwebservices.leg.wa.gov"
    headers_default = {
        "User-Agent": "jeanne-machine/1.0 (rental policy tracker)",
        "Accept": "application/xml,text/xml,*/*",
    }

    # WSL has multiple .asmx services; the housing/topical index methods could
    # live on any of them. Probe the ones most likely to expose bill/topic
    # discovery methods.
    candidate_services = [
        "LegislationService",
        "LegislationDocumentService",
        "SponsorService",
        "BillSummaryService",
        "AmendmentService",
        "LegislativeCalendarService",
        "CommitteeMeetingService",
        "CommitteeActionService",
        "LegislativeDocumentService",
    ]

    import re

    services_summary = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for svc in candidate_services:
            url = f"{base}/{svc}.asmx"
            try:
                resp = await client.get(url, headers=headers_default)
                # ASMX help page links every method as <a href="...?op=MethodName">
                methods = sorted(set(re.findall(r"\?op=([A-Za-z0-9_]+)", resp.text)))
                services_summary.append(
                    {
                        "service": svc,
                        "url": url,
                        "status": resp.status_code,
                        "method_count": len(methods),
                        "methods": methods,
                    }
                )
            except Exception as e:
                services_summary.append(
                    {
                        "service": svc,
                        "url": url,
                        "status": None,
                        "method_count": 0,
                        "methods": [],
                        "error": f"{type(e).__name__}: {str(e)[:200]}",
                    }
                )

    # Also re-confirm the known-good GetLegislation call still works.
    known_good: dict = {}
    list_call: dict = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{base}/LegislationService.asmx/GetLegislation",
                params={"biennium": biennium, "billNumber": bill_number},
                headers=headers_default,
            )
            known_good = {
                "status": resp.status_code,
                "snippet": resp.text[:500],
            }
        except Exception as e:
            known_good = {"error": f"{type(e).__name__}: {str(e)[:200]}"}

        # Try the bulk-list method wa_leg uses, with several since-date formats
        # so we can see which one returns non-zero results.
        list_variants = [
            ("sinceDate=2025-01-01", {"biennium": biennium, "sinceDate": "2025-01-01"}),
            ("sinceDate=2024-01-01", {"biennium": biennium, "sinceDate": "2024-01-01"}),
            ("sinceDate=2025-01-01T00:00:00", {"biennium": biennium, "sinceDate": "2025-01-01T00:00:00"}),
            ("SinceDate=2025-01-01 (PascalCase)", {"biennium": biennium, "SinceDate": "2025-01-01"}),
        ]
        list_call = {"variants": []}
        for label, params in list_variants:
            try:
                resp = await client.get(
                    f"{base}/LegislationService.asmx/GetLegislationInfoIntroducedSince",
                    params=params,
                    headers=headers_default,
                )
                list_call["variants"].append(
                    {
                        "label": label,
                        "url": str(resp.request.url),
                        "status": resp.status_code,
                        "snippet": resp.text[:1500],
                    }
                )
            except Exception as e:
                list_call["variants"].append(
                    {
                        "label": label,
                        "status": None,
                        "error": f"{type(e).__name__}: {str(e)[:200]}",
                    }
                )

    return {
        "biennium": biennium,
        "services": services_summary,
        "known_good_GetLegislation": known_good,
        "GetLegislationInfoIntroducedSince": list_call,
    }


@app.get("/admin/backfill-bill")
async def admin_backfill_bill(
    state: str = Query(..., description="Two-letter state code, e.g. wa"),
    identifier: str = Query(..., description="Bill identifier, e.g. HB1217 or SB26-054"),
    token: str | None = Query(default=None),
):
    """Surgical backfill: fetch one specific bill from Open States and ingest it.

    Bypasses the normal time-window and pagination flow. Useful when a known
    bill isn't being picked up by routine ingest.

    Usage:
      /admin/backfill-bill?state=wa&identifier=HB1217&token=YOUR_TOKEN
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    import httpx

    from adapters.openstates import OpenStatesAdapter
    from audit import _find_os_bill
    from enrichment.pipeline import ingest_raw_doc

    async with httpx.AsyncClient(timeout=60.0) as client:
        bill = await _find_os_bill(client, state.lower(), identifier)
    if not bill:
        return {
            "status": "not_found",
            "message": f"Open States has no bill matching {state.upper()}:{identifier}",
        }

    adapter = OpenStatesAdapter()
    doc = adapter._normalize_bill(bill, state.lower())
    if not doc:
        return {"status": "normalize_failed", "bill_id": bill["id"]}

    async with async_session() as session:
        raw = await ingest_raw_doc(session, doc)
        await session.commit()
        if not raw:
            return {
                "status": "duplicate",
                "bill_id": bill["id"],
                "message": "Already in DB (content_hash match)",
            }
        return {
            "status": "ingested",
            "bill_id": bill["id"],
            "raw_document_id": raw.id,
            "title": doc.title,
        }


@app.get("/admin/audit/coverage")
async def admin_audit_coverage(
    state: list[str] = Query(default=[]),
    days_back: int = Query(default=30, ge=1, le=730),
    token: str | None = Query(default=None),
):
    """Compare housing-tagged Open States bills to what's in our DB.

    Usage:
      /admin/audit/coverage?token=YOUR_TOKEN&state=co&state=wa&days_back=90

    With no `state` param, runs against all 50 jurisdictions — slow, may
    exceed Railway's request timeout. Pass one or more `state=XX` for a
    fast targeted run.
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    from adapters.openstates import ALL_STATES
    from audit import coverage

    states = [s.lower() for s in state] if state else ALL_STATES
    return await coverage(states, days_back)


@app.get("/admin/audit/trace")
async def admin_audit_trace(
    bill: list[str] = Query(default=[]),
    rerun_classifier: bool = Query(default=True),
    token: str | None = Query(default=None),
):
    """Trace specific bills through the pipeline.

    Usage:
      /admin/audit/trace?token=YOUR_TOKEN&bill=CO:SB26-054&bill=WA:HB1217

    `rerun_classifier=true` (default) re-runs the Haiku relevance check on
    the stored raw_text when no PolicyItem exists, so you can see what
    verdict it would give now.
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    if not bill:
        return JSONResponse(
            status_code=400,
            content={"error": "Provide at least one bill, e.g. ?bill=CO:SB26-054"},
        )

    from audit import trace

    return await trace(bill, rerun_classifier)


@app.get("/admin/reset-raw")
async def reset_raw_documents(
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Delete all raw documents and policy items to start fresh.

    Usage: /admin/reset-raw?token=YOUR_TOKEN
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    from storage.models import DigestSend

    await session.execute(text("DELETE FROM digest_send"))
    await session.execute(text("DELETE FROM policy_item"))
    await session.execute(text("DELETE FROM raw_document"))
    await session.commit()

    return {"status": "ok", "message": "All raw documents and policy items deleted. Run the pipeline again to re-ingest."}


# ── Cron: Daily Pipeline ──────────────────────────────────────────


@app.get("/admin/cron-daily")
async def cron_daily(token: str | None = Query(default=None)):
    """Cron-friendly endpoint: ingest last 3 days + enrich up to 50 docs.

    Set up a Railway cron service or external cron to hit this daily:
      GET /admin/cron-daily?token=YOUR_TOKEN

    Uses a 3-day lookback (not 1) to catch items published on weekends
    or that appeared late in a feed.
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_pipeline_task(days_back=3, batch_size=300))
    return {"status": "started", "message": "Daily cron pipeline started (3 days back, 300 enrichment batch)."}


@app.get("/admin/cron-weekly-digest")
async def cron_weekly_digest(token: str | None = Query(default=None)):
    """Cron-friendly endpoint: send weekly digest to all active subscribers.

    Set up a cron to hit this every Monday morning:
      GET /admin/cron-weekly-digest?token=YOUR_TOKEN
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_digest_task("weekly"))
    return {"status": "started", "message": "Weekly digest task started."}


# ── Admin: Slack Digest ────────────────────────────────────────────


@app.get("/admin/send-slack-digest")
async def send_slack_digest(
    frequency: str = Query(default="weekly"),
    days_back: int = Query(default=0, ge=0, le=90),
    token: str | None = Query(default=None),
):
    """Send a digest to the configured Slack webhook.

    Usage: /admin/send-slack-digest?frequency=weekly&token=YOUR_TOKEN

    - frequency: daily|weekly — controls default lookback window
    - days_back: override lookback (e.g. days_back=30 for first send)
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    if not settings.slack_webhook_url:
        return JSONResponse(
            status_code=400,
            content={"error": "SLACK_WEBHOOK_URL not configured. Set it on Railway and redeploy."},
        )

    asyncio.create_task(_run_slack_digest_task(frequency, days_back))
    return {
        "status": "started",
        "message": f"Slack digest ({frequency}) task started. Check /admin/pipeline-status for results.",
    }


@app.get("/admin/cron-weekly-slack")
async def cron_weekly_slack(token: str | None = Query(default=None)):
    """Cron endpoint for weekly Slack digest."""
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})
    if not settings.slack_webhook_url:
        return JSONResponse(status_code=400, content={"error": "SLACK_WEBHOOK_URL not configured"})
    asyncio.create_task(_run_slack_digest_task("weekly", 0))
    return {"status": "started", "message": "Weekly Slack digest task started."}


@app.get("/admin/cron-daily-slack")
async def cron_daily_slack(token: str | None = Query(default=None)):
    """Cron endpoint for daily Slack digest."""
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})
    if not settings.slack_webhook_url:
        return JSONResponse(status_code=400, content={"error": "SLACK_WEBHOOK_URL not configured"})
    asyncio.create_task(_run_slack_digest_task("daily", 0))
    return {"status": "started", "message": "Daily Slack digest task started."}


async def _run_slack_digest_task(frequency: str, days_back: int):
    """Background task: build and send a digest to Slack."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"sent": False, "item_count": 0, "errors": []}

    try:
        from digest.slack import build_slack_digest, send_to_slack

        async with async_session() as session:
            lookback = timedelta(days=days_back) if days_back > 0 else None
            blocks, item_ids = await build_slack_digest(session, subscription=None, lookback=lookback)

            results["item_count"] = len(item_ids)

            fallback_text = f"TT Policy Tracker {frequency} digest — {len(item_ids)} items"
            ok = await send_to_slack(settings.slack_webhook_url, blocks, fallback_text=fallback_text)
            results["sent"] = ok

            if not ok:
                results["errors"].append("Slack webhook returned non-200 or non-'ok'")

    except Exception as e:
        results["errors"].append(f"slack digest error: {type(e).__name__}: {str(e)[:300]}")
        logger.error(f"Slack digest failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


# ── Admin: Digest ──────────────────────────────────────────────────


@app.get("/admin/send-digest")
async def send_digest(
    frequency: str = Query(default="weekly"),
    token: str | None = Query(default=None),
):
    """Trigger a digest email for all active subscriptions of the given frequency.

    Usage: /admin/send-digest?frequency=weekly&token=YOUR_TOKEN

    If no subscriptions exist, creates a default one for the configured
    DIGEST_RECIPIENT.
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    if frequency not in ("daily", "weekly"):
        return JSONResponse(status_code=400, content={"error": "frequency must be 'daily' or 'weekly'"})

    asyncio.create_task(_run_digest_task(frequency))
    return {"status": "started", "message": f"Digest ({frequency}) task started. Check /admin/pipeline-status for results."}


async def _run_digest_task(frequency: str):
    """Background task: build and send digests for all matching subscriptions."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"sent": 0, "skipped": 0, "errors": []}

    try:
        from digest.builder import build_digest
        from digest.sender import send_via_postmark
        from storage.models import DigestSend

        async with async_session() as session:
            query = select(Subscription).where(
                Subscription.active.is_(True),
                Subscription.frequency == frequency,
            )
            result = await session.execute(query)
            subs = result.scalars().all()

            # Auto-create a default subscription if none exist
            if not subs:
                default_sub = Subscription(
                    user_id="admin",
                    email=settings.digest_recipient,
                    frequency=frequency,
                    active=True,
                )
                session.add(default_sub)
                await session.flush()
                subs = [default_sub]
                logger.info(f"Created default {frequency} subscription for {settings.digest_recipient}")

            for sub in subs:
                try:
                    html, item_ids = await build_digest(session, sub)

                    if not item_ids:
                        results["skipped"] += 1
                        logger.info(f"No new items for {sub.email}")
                        continue

                    subject = f"TT Policy Tracker — {frequency.title()} Digest ({len(item_ids)} items)"
                    message_id = await send_via_postmark(sub.email, subject, html)

                    digest_send = DigestSend(
                        subscription_id=sub.id,
                        item_ids=item_ids,
                        message_id=message_id,
                    )
                    session.add(digest_send)
                    sub.last_sent_at = datetime.utcnow()
                    results["sent"] += 1
                    logger.info(f"Digest sent to {sub.email} ({len(item_ids)} items)")

                except Exception as e:
                    err = f"digest for {sub.email}: {str(e)[:300]}"
                    logger.error(err)
                    results["errors"].append(err)

            await session.commit()

    except Exception as e:
        results["errors"].append(f"digest error: {str(e)[:300]}")

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


# ── Law Snapshots ──────────────────────────────────────────────────


@app.get("/api/laws")
async def list_laws(
    jurisdiction_id: int | None = None,
    state: str | None = None,
    topic: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Browse current law snapshots by jurisdiction and/or topic."""
    query = select(LawSnapshot).order_by(LawSnapshot.jurisdiction_id, LawSnapshot.topic)

    if jurisdiction_id:
        query = query.where(LawSnapshot.jurisdiction_id == jurisdiction_id)
    if topic:
        query = query.where(LawSnapshot.topic == topic)
    if state:
        query = query.join(Jurisdiction).where(Jurisdiction.state_code == state.upper())

    result = await session.execute(query)
    snapshots = result.scalars().all()

    return {
        "snapshots": [
            {
                "id": s.id,
                "jurisdiction_id": s.jurisdiction_id,
                "topic": s.topic,
                "headline": s.headline,
                "summary": s.summary,
                "key_facts": s.key_facts,
                "statutory_references": s.statutory_references,
                "source_item_ids": s.source_item_ids,
                "confidence": s.confidence,
                "caveats": s.caveats,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in snapshots
        ]
    }


@app.get("/api/laws/matrix")
async def laws_matrix(session: AsyncSession = Depends(get_session)):
    """Return a matrix of (jurisdiction × topic) with coverage indicators.

    Used by the dashboard to render a heatmap of which
    jurisdiction+topic pairs have synthesized laws, and how confident.
    """
    from enrichment.law_synthesizer import TOPICS, TOPIC_LABELS

    # Get all jurisdictions that have any policy items
    jur_q = (
        select(Jurisdiction)
        .join(PolicyItem, PolicyItem.jurisdiction_id == Jurisdiction.id)
        .distinct()
        .order_by(Jurisdiction.level, Jurisdiction.name)
    )
    jur_result = await session.execute(jur_q)
    jurisdictions = list(jur_result.scalars().all())

    # Get all snapshots
    snapshot_result = await session.execute(select(LawSnapshot))
    snapshots = list(snapshot_result.scalars().all())
    by_key = {(s.jurisdiction_id, s.topic): s for s in snapshots}

    matrix = []
    for jur in jurisdictions:
        row = {
            "jurisdiction_id": jur.id,
            "jurisdiction_name": jur.name,
            "jurisdiction_level": jur.level,
            "state_code": jur.state_code,
            "topics": {},
        }
        for topic in TOPICS:
            snap = by_key.get((jur.id, topic))
            if snap:
                row["topics"][topic] = {
                    "confidence": snap.confidence,
                    "headline": snap.headline,
                    "snapshot_id": snap.id,
                }
            else:
                row["topics"][topic] = None
        matrix.append(row)

    return {
        "topics": TOPICS,
        "topic_labels": TOPIC_LABELS,
        "jurisdictions": matrix,
    }


# ── Admin: Refresh Law Snapshots ──────────────────────────────────


@app.get("/admin/refresh-laws")
async def refresh_laws(
    min_items: int = Query(default=1, ge=1),
    max_pairs: int = Query(default=50, le=500),
    token: str | None = Query(default=None),
):
    """Refresh law snapshots by synthesizing them from current PolicyItems.

    Usage: /admin/refresh-laws?min_items=1&max_pairs=50&token=YOUR_TOKEN

    - min_items: only synthesize for (jurisdiction, topic) pairs with at least N items
    - max_pairs: cap on how many snapshots to refresh in this run (each costs ~$0.01)
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_refresh_laws_task(min_items, max_pairs))
    return {
        "status": "started",
        "message": f"Law snapshot refresh started (min_items={min_items}, max_pairs={max_pairs}).",
    }


async def _run_refresh_laws_task(min_items: int, max_pairs: int):
    """Background task: regenerate law snapshots from current PolicyItems."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"synthesized": 0, "skipped": 0, "errors": []}

    try:
        from enrichment.law_synthesizer import (
            find_jurisdiction_topic_pairs_with_items,
            synthesize_law_snapshot,
        )

        async with async_session() as session:
            pairs = await find_jurisdiction_topic_pairs_with_items(session, min_items=min_items)

        logger.info(f"Found {len(pairs)} (jurisdiction, topic) pairs to synthesize")

        # Process each in its own session so one failure doesn't block others
        for jur_id, topic, items in pairs[:max_pairs]:
            try:
                async with async_session() as session:
                    snapshot = await synthesize_law_snapshot(session, jur_id, topic, items)
                    if snapshot:
                        results["synthesized"] += 1
                    else:
                        results["skipped"] += 1
                    await session.commit()
            except Exception as e:
                err = f"synthesize jur={jur_id} topic={topic}: {type(e).__name__}: {str(e)[:200]}"
                logger.error(err)
                results["errors"].append(err)

    except Exception as e:
        results["errors"].append(f"refresh-laws error: {type(e).__name__}: {str(e)[:300]}")
        logger.error(f"Law refresh failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


# ── Weekly Full Pipeline (Friday EOD Cron) ────────────────────────


@app.get("/admin/cron-weekly-full")
async def cron_weekly_full(token: str | None = Query(default=None)):
    """One-shot weekly pipeline: ingest + enrich + refresh laws + Slack digest.

    Designed to be hit once a week (Friday evening UTC recommended):
      cron: 0 23 * * 5  (23:00 UTC = 5pm MT)

    Full sequence:
      1. Ingest last 7 days from all adapters
      2. Enrich up to 500 new raw documents
      3. Refresh law snapshots for any jurisdiction+topic pairs with activity
      4. Send Slack digest of new items (if SLACK_WEBHOOK_URL set)
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_weekly_full_task())
    return {
        "status": "started",
        "message": "Weekly full pipeline started: ingest → enrich → refresh laws → Slack.",
    }


async def _run_weekly_full_task():
    """Background task: complete end-to-end weekly run."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {
        "ingested": 0,
        "enriched": 0,
        "irrelevant": 0,
        "laws_synthesized": 0,
        "slack_sent": False,
        "slack_item_count": 0,
        "errors": [],
    }

    try:
        # Step 1 + 2: ingest + enrich (reuse existing pipeline)
        from adapters.congress import CongressAdapter
        from adapters.courtlistener import CourtListenerAdapter
        from adapters.federal_register import FederalRegisterAdapter
        from adapters.legistar import LegistarAdapter
        from adapters.openstates import ALL_STATES, OpenStatesAdapter
        from enrichment.pipeline import enrich_document, ingest_raw_doc

        since = datetime.utcnow() - timedelta(days=7)
        os_states = ALL_STATES if settings.openstates_scope == "all" else None
        adapters = [
            OpenStatesAdapter(states=os_states),
            CongressAdapter(),
            FederalRegisterAdapter(),
            LegistarAdapter(),
        ]
        if settings.courtlistener_api_token:
            adapters.append(CourtListenerAdapter())

        for adapter in adapters:
            try:
                docs = await adapter.fetch_new_items(since)
                async with async_session() as session:
                    for doc in docs:
                        raw = await ingest_raw_doc(session, doc)
                        if raw:
                            results["ingested"] += 1
                    await session.commit()
            except Exception as e:
                results["errors"].append(f"{adapter.source_name}: {str(e)[:300]}")

        # Enrich the new docs (per-item commit)
        async with async_session() as session:
            query = (
                select(RawDocument.id)
                .where(RawDocument.classified_at.is_(None))
                .order_by(RawDocument.fetched_at.desc())
                .limit(500)
            )
            result = await session.execute(query)
            raw_ids = list(result.scalars().all())

        for raw_id in raw_ids:
            try:
                async with async_session() as session:
                    raw = await session.get(RawDocument, raw_id)
                    if not raw:
                        continue
                    item = await enrich_document(session, raw)
                    if item:
                        results["enriched"] += 1
                    else:
                        results["irrelevant"] += 1
                    await session.commit()
            except Exception as e:
                results["errors"].append(f"enrich {raw_id}: {str(e)[:200]}")

        # Step 3: refresh law snapshots for pairs with new activity
        try:
            from enrichment.law_synthesizer import (
                find_jurisdiction_topic_pairs_with_items,
                synthesize_law_snapshot,
            )

            async with async_session() as session:
                pairs = await find_jurisdiction_topic_pairs_with_items(session, min_items=1)

            for jur_id, topic, items in pairs[:50]:
                try:
                    async with async_session() as session:
                        snap = await synthesize_law_snapshot(session, jur_id, topic, items)
                        if snap:
                            results["laws_synthesized"] += 1
                        await session.commit()
                except Exception as e:
                    results["errors"].append(f"synth {jur_id}/{topic}: {str(e)[:150]}")
        except Exception as e:
            results["errors"].append(f"law synth stage: {str(e)[:300]}")

        # Step 4: Slack digest
        if settings.slack_webhook_url:
            try:
                from digest.slack import build_slack_digest, send_to_slack

                async with async_session() as session:
                    blocks, item_ids = await build_slack_digest(
                        session, subscription=None, lookback=timedelta(days=7)
                    )
                    results["slack_item_count"] = len(item_ids)
                    ok = await send_to_slack(
                        settings.slack_webhook_url,
                        blocks,
                        fallback_text=f"TT Policy Tracker weekly digest ({len(item_ids)} items)",
                    )
                    results["slack_sent"] = ok
            except Exception as e:
                results["errors"].append(f"slack stage: {str(e)[:300]}")

    except Exception as e:
        results["errors"].append(f"weekly pipeline error: {str(e)[:300]}")
        logger.error(f"Weekly pipeline failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }


# ── Content Drafts ─────────────────────────────────────────────────

from storage.models import ContentDraft


@app.get("/api/drafts")
async def list_drafts(
    status: str | None = None,
    content_type: str | None = None,
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List content drafts with optional status/type filters."""
    query = select(ContentDraft).order_by(ContentDraft.generated_at.desc())
    if status:
        query = query.where(ContentDraft.status == status)
    if content_type:
        query = query.where(ContentDraft.content_type == content_type)

    result = await session.execute(query.limit(limit))
    drafts = result.scalars().all()

    return {
        "drafts": [
            {
                "id": d.id,
                "policy_item_id": d.policy_item_id,
                "content_type": d.content_type,
                "title": d.title,
                "body": d.body,
                "seo_description": d.seo_description,
                "suggested_tags": d.suggested_tags,
                "status": d.status,
                "generated_at": d.generated_at.isoformat() if d.generated_at else None,
            }
            for d in drafts
        ]
    }


@app.post("/api/drafts/{draft_id}/status")
async def update_draft_status(
    draft_id: int,
    new_status: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Update a draft's status (approve, reject, publish)."""
    valid = {"draft", "approved", "rejected", "published"}
    if new_status not in valid:
        return JSONResponse(status_code=400, content={"error": f"status must be one of {valid}"})

    draft = await session.get(ContentDraft, draft_id)
    if not draft:
        return JSONResponse(status_code=404, content={"error": "draft not found"})

    draft.status = new_status
    await session.commit()
    return {"id": draft_id, "status": new_status}


@app.get("/admin/generate-drafts")
async def generate_drafts(
    min_impact: str = Query(default="high"),
    max_drafts: int = Query(default=5, le=20),
    token: str | None = Query(default=None),
):
    """Generate blog post drafts from high-impact PolicyItems.

    Usage: /admin/generate-drafts?min_impact=high&max_drafts=5
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    asyncio.create_task(_run_draft_generation(min_impact, max_drafts))
    return {
        "status": "started",
        "message": f"Draft generation started (min_impact={min_impact}, max_drafts={max_drafts}).",
    }


async def _run_draft_generation(min_impact: str, max_drafts: int):
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"generated": 0, "errors": []}

    try:
        from enrichment.content_drafter import generate_drafts_for_high_impact

        async with async_session() as session:
            drafts = await generate_drafts_for_high_impact(
                session, min_impact=min_impact, max_drafts=max_drafts
            )
            results["generated"] = len(drafts)
            await session.commit()
    except Exception as e:
        results["errors"].append(f"draft gen error: {type(e).__name__}: {str(e)[:300]}")

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }
