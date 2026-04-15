"""FastAPI internal API for the TT Policy Tracker."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from storage.database import get_session
from storage.models import Base, Jurisdiction, PolicyItem, Subscription

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
