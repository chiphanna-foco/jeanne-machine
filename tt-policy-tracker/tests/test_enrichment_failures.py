"""Failures in Claude calls must be visible and must not consume docs.

No DB and no network: the Anthropic client and the SQLAlchemy session are
mocked. These pin the rule from the 2026-09 audit: an API failure leaves
`classified_at` null (retry next run) and counts as `api_errors`; only a real
verdict, or output that stays unparseable after one retry, sets it.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from enrichment import claude_client
from enrichment.claude_client import EnrichmentAPIError
from enrichment.pipeline import api_should_stop, enrich_counted, new_run_counters
from storage.models import RawDocument

RELEVANT = {"relevant": True, "topics": ["security_deposit"], "confidence": 0.9}
IRRELEVANT = {"relevant": False, "topics": [], "confidence": 0.9}
SUMMARY = {
    "title": "Colorado caps security deposits",
    "summary": "Caps deposits at one month.",
    "impact_score": "high",
    "impact_reasoning": "Applies to all landlords.",
    "topics": ["security_deposit"],
    "action_needed": "monitor",
    "effective_date": None,
}


def _reply(payload) -> SimpleNamespace:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _status_error(cls, code: int):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(code, request=req), body=None)


@pytest.fixture
def claude(monkeypatch):
    """Patch the SDK client. Set `.side_effect` to a list of replies/errors."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    create = AsyncMock()
    client = MagicMock()
    client.messages.create = create
    monkeypatch.setattr(claude_client.anthropic, "AsyncAnthropic", lambda **kw: client)
    return create


def _session():
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None  # no PolicyItem yet
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


def _raw() -> RawDocument:
    # No "Subjects:" line, so the housing-subject override does not kick in.
    return RawDocument(id=1, external_id="test-doc-1", raw_text="An act concerning deposits.")


async def test_classifier_api_error_leaves_doc_queued_and_counts(claude):
    claude.side_effect = [_status_error(anthropic.RateLimitError, 429)]
    raw, counters = _raw(), new_run_counters()

    item = await enrich_counted(_session(), raw, counters)

    assert item is None
    assert raw.classified_at is None  # retried next run
    assert counters["api_errors"] == 1
    assert counters["processed"] == 0 and counters["irrelevant"] == 0


async def test_summarizer_failure_leaves_doc_retryable(claude):
    claude.side_effect = [_reply(RELEVANT), _status_error(anthropic.InternalServerError, 500)]
    raw, counters = _raw(), new_run_counters()

    item = await enrich_counted(_session(), raw, counters)

    assert item is None
    assert raw.classified_at is None
    assert counters["api_errors"] == 1
    assert counters["irrelevant"] == 0  # not miscounted as irrelevant


async def test_real_irrelevant_verdict_sets_classified_at(claude):
    claude.side_effect = [_reply(IRRELEVANT)]
    raw, counters = _raw(), new_run_counters()

    item = await enrich_counted(_session(), raw, counters)

    assert item is None
    assert raw.classified_at is not None
    assert counters["irrelevant"] == 1 and counters["processed"] == 1
    assert counters["api_errors"] == 0


async def test_relevant_and_summarized_creates_item(claude):
    claude.side_effect = [_reply(RELEVANT), _reply(SUMMARY)]
    raw, counters = _raw(), new_run_counters()

    item = await enrich_counted(_session(), raw, counters)

    assert item is not None and item.title == SUMMARY["title"]
    assert raw.classified_at is not None
    assert counters["relevant"] == 1 and counters["processed"] == 1


async def test_bad_json_retries_once_then_succeeds(claude):
    claude.side_effect = [_reply("not json"), _reply(IRRELEVANT)]
    raw, counters = _raw(), new_run_counters()

    await enrich_counted(_session(), raw, counters)

    assert claude.await_count == 2
    assert counters["parse_errors"] == 0 and counters["irrelevant"] == 1


async def test_bad_json_twice_consumes_doc_and_records_it(claude):
    claude.side_effect = [_reply("not json"), _reply("still not json")]
    raw, counters = _raw(), new_run_counters()

    item = await enrich_counted(_session(), raw, counters)

    assert item is None
    assert raw.classified_at is not None  # cannot retry forever
    assert counters["parse_errors"] == 1
    assert counters["parse_failed_ids"] == ["test-doc-1"]
    assert counters["processed"] == 0


async def test_empty_key_is_an_api_error_without_a_network_call(claude, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    raw, counters = _raw(), new_run_counters()

    await enrich_counted(_session(), raw, counters)

    claude.assert_not_awaited()
    assert raw.classified_at is None
    assert counters["api_errors"] == 1
    assert api_should_stop(counters)  # definitive: stop the run at once


async def test_auth_error_stops_the_run_at_first_failure(claude):
    claude.side_effect = [_status_error(anthropic.AuthenticationError, 401)]
    counters = new_run_counters()

    await enrich_counted(_session(), _raw(), counters)

    assert counters["api_stop_reason"].startswith("auth")


async def test_transient_errors_stop_after_five_in_a_row(claude):
    claude.side_effect = [_status_error(anthropic.RateLimitError, 429)] * 5
    counters = new_run_counters()

    for _ in range(4):
        await enrich_counted(_session(), _raw(), counters)
        assert not api_should_stop(counters)
    await enrich_counted(_session(), _raw(), counters)

    assert api_should_stop(counters)
    assert counters["api_errors"] == 5


@pytest.mark.parametrize(
    "exc, kind",
    [
        (_status_error(anthropic.AuthenticationError, 401), "auth"),
        (_status_error(anthropic.PermissionDeniedError, 403), "permission"),
        (_status_error(anthropic.RateLimitError, 429), "rate_limit"),
        (_status_error(anthropic.InternalServerError, 503), "server"),
        (_status_error(anthropic.BadRequestError, 400), "status"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "connection"),
    ],
)
async def test_sdk_errors_map_to_kinds(claude, exc, kind):
    claude.side_effect = [exc]
    with pytest.raises(EnrichmentAPIError) as info:
        await claude_client.create_message(model="m", max_tokens=1, messages=[])
    assert info.value.kind == kind


async def test_law_synthesizer_raises_instead_of_returning_none(claude):
    from enrichment.law_synthesizer import synthesize_law_snapshot

    claude.side_effect = [_status_error(anthropic.RateLimitError, 429)]
    session = _session()
    session.get = AsyncMock(return_value=None)
    item = SimpleNamespace(
        discovered_at=None, published_at=None, impact_score="high",
        title="t", summary="s", impact_reasoning="r", id=7,
    )

    with pytest.raises(EnrichmentAPIError):
        await synthesize_law_snapshot(session, 1, "security_deposit", [item])


async def test_content_drafter_counts_failures(claude):
    from enrichment.content_drafter import generate_drafts_for_high_impact

    claude.side_effect = [_reply("nope"), _reply("nope again")]
    item = SimpleNamespace(
        id=3, title="t", summary="s", impact_score="high", impact_reasoning="r",
        topic_tags=["eviction"], action_needed="urgent", source_url=None,
    )
    session = _session()
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = [item]
    no_draft = MagicMock()
    no_draft.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(side_effect=[items_result, no_draft])
    counters: dict = {}

    drafts = await generate_drafts_for_high_impact(session, counters=counters)

    assert drafts == []
    assert counters == {"parse_errors": 1}


async def test_health_reports_sha_models_and_key_presence(monkeypatch):
    from api.main import health

    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    monkeypatch.setattr(settings, "anthropic_api_key", "secret-value")
    body = await health()

    assert body["status"] == "ok" and body["service"] == "jeanne-machine"
    assert body["git_sha"] == "abc123"
    assert body["classifier_model"] == settings.classifier_model
    assert body["summarizer_model"] == settings.summarizer_model
    assert "synthesizer_model" in body
    assert body["anthropic_key_configured"] is True
    assert "secret-value" not in json.dumps(body)

    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA")
    assert (await health())["git_sha"] == "unknown"
