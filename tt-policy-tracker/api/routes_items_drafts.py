"""API key guard for /api/* and per-item blog-draft endpoints.

Kept in its own module so main.py only needs three lines to wire it in.

Key guard
---------
Every /api/* request must carry header `X-Jeanne-Key` equal to env var
JEANNE_API_KEY. The Vercel app adds it server-side in its /backend proxy, so
browsers never see the key.

- /health, /, /docs and /admin/* are NOT checked here. /admin/* keeps its own
  `?token=ADMIN_TOKEN` check, which the GitHub Actions crons use.
- JEANNE_API_KEY unset or empty: /api/* fails CLOSED (503) and logs one clear
  error. There is no dev-mode bypass.
- JEANNE_API_KEY_MODE=warn is a rollout grace mode: a missing or wrong key is
  logged (path + user agent, never the key) and the request is ALLOWED. Any
  other value, or unset, means enforce: a missing or wrong key gets 401.

The settings are read from os.environ on each request, not from config.py,
so this module does not touch config.py (another PR owns it) and tests can
monkeypatch the environment.

Draft endpoints
---------------
POST /api/items/{id}/drafts  start the existing blog drafter in the background
GET  /api/items/{id}/drafts  poll: draft id + status, or "drafting", or "none"
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.database import async_session, get_session
from storage.models import ContentDraft, PolicyItem

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-Jeanne-Key"
_GUARDED_PREFIX = "/api/"

_logged_unset_key = False
_warned_paths: set[str] = set()


def _configured_key() -> str:
    return os.environ.get("JEANNE_API_KEY", "").strip()


def _warn_mode() -> bool:
    return os.environ.get("JEANNE_API_KEY_MODE", "").strip().lower() == "warn"


def _key_matches(presented: str | None, expected: str) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def install_api_key_guard(app: FastAPI) -> None:
    """Register the /api/* key check as HTTP middleware on `app`."""

    @app.middleware("http")
    async def _api_key_guard(request: Request, call_next):
        global _logged_unset_key
        path = request.url.path
        # CORS preflights carry no custom headers; let CORSMiddleware answer.
        if not path.startswith(_GUARDED_PREFIX) or request.method == "OPTIONS":
            return await call_next(request)

        expected = _configured_key()
        if not expected:
            if not _logged_unset_key:
                logger.error(
                    "JEANNE_API_KEY is not set. Every /api/* request is refused (503) "
                    "until it is set on Railway. /health and /admin/* are unaffected."
                )
                _logged_unset_key = True
            return JSONResponse(
                status_code=503,
                content={"error": "API key not configured on server; /api/* is closed."},
            )

        if _key_matches(request.headers.get(API_KEY_HEADER), expected):
            return await call_next(request)

        if _warn_mode():
            # Grace mode: allow, but leave a receipt so keyless callers can be found.
            if path not in _warned_paths:
                _warned_paths.add(path)
                logger.warning(
                    "JEANNE_API_KEY_MODE=warn: allowed /api request with missing or wrong "
                    "%s header: %s %s (user-agent=%r). This will be 401 under enforce.",
                    API_KEY_HEADER,
                    request.method,
                    path,
                    request.headers.get("user-agent", ""),
                )
            return await call_next(request)

        return JSONResponse(status_code=401, content={"error": "missing or invalid API key"})


# ── Per-item blog drafts ────────────────────────────────────────────

router = APIRouter()

# Item ids with a draft job in flight. Guards against repeated clicks starting
# duplicate jobs. In-process only: Railway runs one uvicorn process today. The
# unique constraint on content_draft.policy_item_id is the hard backstop.
_drafting: set[int] = set()
_last_error: dict[int, str] = {}


def _draft_dict(d: ContentDraft) -> dict:
    return {
        "id": d.id,
        "policy_item_id": d.policy_item_id,
        "content_type": d.content_type,
        "title": d.title,
        "status": d.status,
        "generated_at": d.generated_at.isoformat() if d.generated_at else None,
    }


async def _get_item(session: AsyncSession, item_id: int) -> PolicyItem | None:
    return await session.get(PolicyItem, item_id)


async def _find_draft(session: AsyncSession, item_id: int) -> ContentDraft | None:
    # policy_item_id is unique on content_draft, so an item has at most one
    # draft of any type.
    result = await session.execute(
        select(ContentDraft).where(ContentDraft.policy_item_id == item_id)
    )
    return result.scalars().first()


async def _run_blog_draft(item_id: int) -> None:
    """Background job: run the existing blog drafter for one item."""
    from enrichment.content_drafter import generate_blog_draft

    try:
        async with async_session() as session:
            item = await _get_item(session, item_id)
            if item is None:
                _last_error[item_id] = "item not found"
                return
            draft = await generate_blog_draft(session, item)
            await session.commit()
            if draft is None and await _find_draft(session, item_id) is None:
                _last_error[item_id] = "drafter returned no draft; see Railway logs"
                logger.error("Blog draft for item %s produced nothing", item_id)
    except Exception as e:  # noqa: BLE001 - surface every failure to the poller
        _last_error[item_id] = f"{type(e).__name__}: {str(e)[:200]}"
        logger.error("Blog draft for item %s failed: %s", item_id, e, exc_info=True)
    finally:
        _drafting.discard(item_id)


def _existing_response(draft: ContentDraft) -> JSONResponse:
    body = {"status": "exists", "draft": _draft_dict(draft)}
    if draft.content_type != "blog_post":
        body["note"] = (
            f"This item already has a {draft.content_type} draft; "
            "only one draft per item is allowed."
        )
    return JSONResponse(status_code=200, content=body)


@router.post("/api/items/{item_id}/drafts")
async def create_item_draft(
    item_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Start a blog draft for one item. 202 if started, 200 if one exists."""
    existing = await _find_draft(session, item_id)
    if existing is not None:
        return _existing_response(existing)

    if item_id in _drafting:
        return JSONResponse(status_code=202, content={"status": "drafting", "item_id": item_id})

    if await _get_item(session, item_id) is None:
        return JSONResponse(status_code=404, content={"error": "item not found"})

    _drafting.add(item_id)
    _last_error.pop(item_id, None)
    background_tasks.add_task(_run_blog_draft, item_id)
    return JSONResponse(status_code=202, content={"status": "drafting", "item_id": item_id})


@router.get("/api/items/{item_id}/drafts")
async def get_item_draft(item_id: int, session: AsyncSession = Depends(get_session)):
    """Poll a draft: exists (with id), drafting, failed, or none."""
    existing = await _find_draft(session, item_id)
    if existing is not None:
        return _existing_response(existing)
    if item_id in _drafting:
        return {"status": "drafting", "item_id": item_id}
    if item_id in _last_error:
        return {"status": "failed", "item_id": item_id, "error": _last_error[item_id]}
    return {"status": "none", "item_id": item_id}
