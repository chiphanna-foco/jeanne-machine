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
from storage.models import Base, Jurisdiction, PolicyItem, RawDocument, Subscription

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
    return {"status": "ok", "service": "tt-policy-tracker"}


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
    days_back: int = Query(default=30, le=90),
    batch_size: int = Query(default=50, le=200),
    token: str | None = Query(default=None),
):
    """Trigger ingestion + enrichment in one call.

    Usage: /admin/run-pipeline?days_back=30&batch_size=50&token=YOUR_TOKEN
    """
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})

    # Run in background so the request doesn't timeout
    asyncio.create_task(_run_pipeline_task(days_back, batch_size))

    return {
        "status": "started",
        "message": f"Pipeline started: ingesting {days_back} days back, then enriching up to {batch_size} docs. Check /admin/pipeline-status for progress.",
    }


# Simple in-memory status tracking
_pipeline_status = {"running": False, "last_run": None, "last_result": None}


@app.get("/admin/pipeline-status")
async def pipeline_status(token: str | None = Query(default=None)):
    if not _check_admin_token(token):
        return JSONResponse(status_code=403, content={"error": "Invalid admin token"})
    return _pipeline_status


async def _run_pipeline_task(days_back: int, batch_size: int):
    """Background task: ingest from all adapters, then enrich."""
    global _pipeline_status
    _pipeline_status = {"running": True, "last_run": datetime.utcnow().isoformat(), "last_result": None}

    results = {"ingested": 0, "enriched": 0, "irrelevant": 0, "errors": []}

    try:
        # ── Step 1: Ingest ──
        from adapters.congress import CongressAdapter
        from adapters.federal_register import FederalRegisterAdapter
        from adapters.openstates import OpenStatesAdapter
        from enrichment.pipeline import enrich_document, ingest_raw_doc

        since = datetime.utcnow() - timedelta(days=days_back)
        adapters = [OpenStatesAdapter(), CongressAdapter(), FederalRegisterAdapter()]

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
            except Exception as e:
                err = f"{adapter.source_name}: {str(e)}"
                logger.error(err, exc_info=True)
                results["errors"].append(err)

        # ── Step 2: Enrich ──
        async with async_session() as session:
            subquery = select(PolicyItem.raw_document_id)
            query = (
                select(RawDocument)
                .where(RawDocument.id.notin_(subquery))
                .order_by(RawDocument.fetched_at.desc())
                .limit(batch_size)
            )
            result = await session.execute(query)
            raw_docs = result.scalars().all()

            for raw in raw_docs:
                try:
                    item = await enrich_document(session, raw)
                    if item:
                        results["enriched"] += 1
                    else:
                        results["irrelevant"] += 1
                except Exception as e:
                    err = f"enrich {raw.external_id}: {str(e)}"
                    logger.error(err)
                    results["errors"].append(err)

            await session.commit()

    except Exception as e:
        results["errors"].append(f"pipeline error: {str(e)}")
        logger.error(f"Pipeline failed: {e}", exc_info=True)

    _pipeline_status = {
        "running": False,
        "last_run": datetime.utcnow().isoformat(),
        "last_result": results,
    }
