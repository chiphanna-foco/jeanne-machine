"""Model settings for Sonnet 5.5 / Opus 5.5, citation checks, pair order,
and funding-only bills. No DB and no network: the SDK client is mocked.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Settings, settings
from enrichment import claude_client, classifier, content_drafter, law_synthesizer, summarizer
from enrichment.claude_client import EnrichmentParseError
from enrichment.keywords import is_funding_bill_title
from enrichment.law_synthesizer import order_pairs_for_refresh, strip_unsupported_citations
from enrichment.pipeline import enrich_counted, new_run_counters
from storage.models import RawDocument

SUMMARY = {
    "title": "t", "summary": "s", "impact_score": "high", "impact_reasoning": "r",
    "topics": ["eviction"], "action_needed": "monitor", "effective_date": None,
}


def _reply(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking=""),  # must be skipped
            SimpleNamespace(type="text", text=text),
        ],
    )


def _patch_client(monkeypatch, module, reply):
    """Patch the one SDK entry point (enrichment.claude_client). `module` is
    kept for readability at call sites. `reply` may be a list of replies."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    if isinstance(reply, list):
        create = AsyncMock(side_effect=reply)
    else:
        create = AsyncMock(return_value=reply)
    client = MagicMock()
    client.messages.create = create
    monkeypatch.setattr(claude_client.anthropic, "AsyncAnthropic", lambda **kw: client)
    return create


# ── Model settings ─────────────────────────────────────────────────


def test_default_models_and_env_overrides(monkeypatch):
    assert settings.classifier_model == "claude-haiku-4-5-20251001"  # unchanged
    assert settings.summarizer_model == "claude-sonnet-5-5"
    assert settings.law_synth_model == "claude-opus-5-5"
    assert settings.drafter_model == "claude-opus-5-5"
    monkeypatch.setenv("LAW_SYNTH_MODEL", "claude-opus-5")
    monkeypatch.setenv("DRAFTER_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("SUMMARIZER_MODEL", "claude-sonnet-5")
    s = Settings()
    assert (s.law_synth_model, s.drafter_model, s.summarizer_model) == (
        "claude-opus-5", "claude-sonnet-5-5", "claude-sonnet-5"
    )


async def test_summarizer_request_shape_and_reads_text_after_thinking(monkeypatch):
    create = _patch_client(monkeypatch, summarizer, _reply(SUMMARY))

    result = await summarizer.summarize_document("doc")

    kw = create.await_args.kwargs
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["thinking"] == {"type": "between_tools"}  # no other field
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["max_tokens"] > 600
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in kw
    assert result["title"] == "t"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
async def test_summarizer_incomplete_answer_is_a_failure(monkeypatch, stop_reason):
    create = _patch_client(monkeypatch, summarizer, _reply(SUMMARY, stop_reason=stop_reason))
    with pytest.raises(EnrichmentParseError, match=f"stop_reason={stop_reason}"):
        await summarizer.summarize_document("doc")
    assert create.await_count == 2  # retried once


async def test_max_tokens_cutoff_is_counted_not_silently_dropped(monkeypatch):
    """Run 36631928623 lost one doc to a summarizer cut-off. It must count."""
    relevant = {"relevant": True, "funding_only": False, "topics": ["eviction"], "confidence": 0.9}
    cut = _reply('{"title": "Colorado caps', stop_reason="max_tokens")
    _patch_client(monkeypatch, summarizer, [_reply(relevant), cut, cut])
    raw = RawDocument(id=1, external_id="ocd-bill/test", raw_text="An act concerning evictions.")
    counters = new_run_counters()

    item = await enrich_counted(_synth_session(), raw, counters)

    assert item is None
    assert counters["parse_errors"] == 1
    assert counters["parse_failed_ids"] == ["ocd-bill/test"]
    assert counters["irrelevant"] == 0 and counters["api_errors"] == 0
    assert raw.classified_at is not None  # consumed after the retry, and listed


async def test_max_tokens_then_full_answer_recovers(monkeypatch):
    create = _patch_client(
        monkeypatch, summarizer, [_reply("{", stop_reason="max_tokens"), _reply(SUMMARY)]
    )
    result = await summarizer.summarize_document("doc")
    assert result["title"] == "t" and create.await_count == 2


def _synth_session():
    session = MagicMock()
    session.get = AsyncMock(return_value=SimpleNamespace(name="Colorado", level="state"))
    no_snapshot = MagicMock()
    no_snapshot.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=no_snapshot)
    session.flush = AsyncMock()
    return session


def _item(id_, title="Deposit bill", summary="Amends C.R.S. § 38-12-103."):
    return SimpleNamespace(
        id=id_, discovered_at=None, published_at=None, impact_score="high",
        title=title, summary=summary, impact_reasoning="r",
    )


async def test_law_synthesizer_uses_opus_high_effort(monkeypatch):
    reply = _reply({"headline": "h", "summary": "s", "key_facts": [], "statutory_references": [],
                    "confidence": "med", "caveats": ""})
    create = _patch_client(monkeypatch, law_synthesizer, reply)

    snap = await law_synthesizer.synthesize_law_snapshot(_synth_session(), 1, "security_deposit", [_item(1)])

    kw = create.await_args.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "high"}
    assert kw["max_tokens"] >= 16000
    assert "thinking" not in kw and "temperature" not in kw
    assert snap is not None


async def test_law_synthesizer_refusal_is_a_counted_failure(monkeypatch):
    _patch_client(monkeypatch, law_synthesizer, _reply("{}", stop_reason="refusal"))
    with pytest.raises(EnrichmentParseError, match="stop_reason=refusal"):
        await law_synthesizer.synthesize_law_snapshot(_synth_session(), 1, "eviction", [_item(1)])


async def test_content_drafter_uses_opus_high_effort(monkeypatch):
    create = _patch_client(
        monkeypatch, content_drafter, _reply({"title": "T", "body": "B"})
    )
    session = _synth_session()
    item = SimpleNamespace(id=3, title="t", summary="s", impact_score="high", impact_reasoning="r",
                           topic_tags=["eviction"], action_needed="urgent", source_url=None)

    draft = await content_drafter.generate_blog_draft(session, item)

    kw = create.await_args.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "high"}
    assert "temperature" not in kw
    assert draft is not None


# ── Citation post-check ────────────────────────────────────────────


def test_citations_not_in_input_are_removed_and_flagged():
    source = "[1] Amends C.R.S. § 38-12-103 and 42 U.S.C. 3604."
    result = {
        "headline": "Deposits capped under § 38-12-103",
        "summary": "Colorado also relies on Colo. Rev. Stat. 13-40-104 for evictions.",
        "key_facts": ["Return within 30 days (§ 38-12-103)", "Cal. Civ. Code § 1950.5 differs"],
        "statutory_references": ["C.R.S. § 38-12-103", "42 U.S.C. § 3604(b)", "CRS § 38-12-999"],
        "caveats": "Recent activity only.",
    }

    out, removed = strip_unsupported_citations(result, source)

    assert out["statutory_references"] == ["C.R.S. § 38-12-103", "42 U.S.C. § 3604(b)"]
    assert out["key_facts"][0] == "Return within 30 days (§ 38-12-103)"
    # Only the citation text goes; the rest of the fact stays.
    assert out["key_facts"][1] == "Cal. Civ. [citation removed: not in source items] differs"
    assert "13-40-104" not in out["summary"]
    assert "[citation removed" in out["summary"]
    assert out["headline"] == "Deposits capped under § 38-12-103"
    assert len(removed) == 3
    assert "3 citation(s) were removed" in out["caveats"]


def test_no_citations_means_no_change():
    result = {"headline": "h", "summary": "HB26-1196 passed.", "key_facts": ["a"],
              "statutory_references": [], "caveats": ""}
    out, removed = strip_unsupported_citations(dict(result), "HB26-1196 text")
    assert removed == [] and out["caveats"] == ""


def test_synthesizer_prompt_limits_citations_to_the_input():
    assert "ONLY if that exact reference appears in the source items" in (
        law_synthesizer.SYNTHESIZER_SYSTEM_PROMPT
    )


# ── Pair ordering for the weekly refresh ───────────────────────────


def test_pairs_with_new_items_first_then_oldest_snapshot():
    now = datetime(2026, 9, 29)
    items = {i: SimpleNamespace(id=i) for i in range(1, 10)}
    pairs = [
        (1, "eviction", [items[1]]),              # snapshot current, fresh
        (2, "eviction", [items[2]]),              # snapshot current, old
        (3, "eviction", [items[3], items[4]]),    # item 4 is new, recent snapshot
        (4, "eviction", [items[5], items[6]]),    # item 6 is new, old snapshot
        (5, "eviction", [items[7]]),              # no snapshot yet
    ]
    snaps = {
        (1, "eviction"): SimpleNamespace(source_item_ids=[1], updated_at=now),
        (2, "eviction"): SimpleNamespace(source_item_ids=[2], updated_at=now - timedelta(days=30)),
        (3, "eviction"): SimpleNamespace(source_item_ids=[3], updated_at=now - timedelta(days=1)),
        (4, "eviction"): SimpleNamespace(source_item_ids=[5], updated_at=now - timedelta(days=20)),
    }

    order = [p[0] for p in order_pairs_for_refresh(pairs, snaps)]

    assert order == [5, 4, 3, 2, 1]


# ── Funding-only bills ─────────────────────────────────────────────


async def test_funding_only_does_not_override_a_relevant_verdict(monkeypatch):
    """relevant=true + funding_only=true is kept: the model's verdict stands."""
    _patch_client(monkeypatch, classifier, [
        _reply({"relevant": True, "funding_only": True, "topics": ["eviction"], "confidence": 0.9}),
        _reply(SUMMARY),
    ])
    result = await classifier.classify_document("HB 1: Rental assistance appropriation")
    assert result["relevant"] is True and result["funding_only"] is True

    raw = RawDocument(id=1, external_id="x", raw_text="HB 1: Budget Act of 2026\nSubjects: Housing")
    counters = new_run_counters()
    _patch_client(monkeypatch, classifier, [
        _reply({"relevant": True, "funding_only": True, "topics": ["eviction"], "confidence": 0.9}),
        _reply(SUMMARY),
    ])
    item = await enrich_counted(_synth_session(), raw, counters)
    assert item is not None and counters["relevant"] == 1


async def test_funding_only_blocks_the_subject_tag_rescue(monkeypatch):
    _patch_client(monkeypatch, classifier, _reply(
        {"relevant": False, "funding_only": True, "topics": [], "confidence": 0.9}
    ))
    raw = RawDocument(id=1, external_id="x", raw_text="HB 7: Housing trust fund\nSubjects: Housing")
    counters = new_run_counters()
    item = await enrich_counted(_synth_session(), raw, counters)
    assert item is None and counters["irrelevant"] == 1


def test_classifier_prompt_asks_for_funding_only():
    assert '"funding_only": true/false' in classifier.CLASSIFIER_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "text, expected",
    [
        ("HB 2: General Appropriations Act for FY 2027", True),
        ("SB 5: Making supplemental appropriations for housing", True),
        ("AB 101: Budget Act of 2026\nSubjects: Housing", True),
        ("HB 1196: Tenant data information\nSubjects: Housing", False),
        ("HB 9: Security deposits\nThis act has no appropriation.", False),
    ],
)
def test_funding_title_backstop(text, expected):
    assert is_funding_bill_title(text) is expected


async def test_funding_title_blocks_the_housing_subject_override(monkeypatch):
    from enrichment import pipeline

    async def fake_classify(text):
        return {"relevant": False, "funding_only": False, "topics": [], "confidence": 0.9}

    monkeypatch.setattr(pipeline, "classify_document", fake_classify)
    summarize = AsyncMock()
    monkeypatch.setattr(pipeline, "summarize_document", summarize)
    session = _synth_session()
    raw = pipeline.RawDocument(
        id=1, external_id="x", raw_text="SB 5: General Appropriations Act\nSubjects: Housing"
    )

    item = await pipeline.enrich_document(session, raw)

    assert item is None
    summarize.assert_not_awaited()


# ── Citation check edge cases (review fixes) ─────────────────────


def test_year_after_code_name_is_not_a_citation():
    from enrichment.law_synthesizer import unsupported_citations

    assert unsupported_citations("Enacted in Session Laws 2024 and the Code 2023 update.", "") == []
    assert unsupported_citations("Colo. Rev. Stat. 2024-1", "") != []  # not a bare year


@pytest.mark.parametrize(
    "text, source",
    [
        ("Under C.R.S. § 38\u201312\u2013103 deposits", "Amends C.R.S. § 38-12-103."),  # en dash out
        ("Under C.R.S. § 38-12-103 deposits", "Amends C.R.S. § 38\u201412\u2014103."),  # em dash in
    ],
)
def test_dashes_are_normalized_on_both_sides(text, source):
    from enrichment.law_synthesizer import unsupported_citations

    assert unsupported_citations(text, source) == []


def test_section_numbers_must_match_as_whole_tokens():
    from enrichment.law_synthesizer import unsupported_citations

    source = "Amends C.R.S. § 38-12-108 and HB 8."
    assert unsupported_citations("See § 8 for details", source) == ["§ 8"]
    assert unsupported_citations("See § 12 for details", source) == ["§ 12"]
    assert unsupported_citations("See § 38-12-108 for details", source) == []
    assert unsupported_citations("See § 38-12-10 for details", source) == ["§ 38-12-10"]


def test_key_fact_keeps_its_text_when_a_citation_is_stripped():
    out, removed = strip_unsupported_citations(
        {"key_facts": ["Deposit is due back in 30 days under § 99-1-1, per the bill."],
         "statutory_references": [], "headline": "", "summary": "", "caveats": ""},
        "Deposit returns within 30 days.",
    )
    assert out["key_facts"] == [
        "Deposit is due back in 30 days under [citation removed: not in source items], per the bill."
    ]
    assert len(removed) == 1


# ── Rotation: failed pairs go last (review fix) ──────────────────


def test_failed_pair_drops_behind_pairs_that_have_not_failed(monkeypatch):
    monkeypatch.setattr(law_synthesizer, "_failed_last_attempt", {(5, "eviction")})
    items = {i: SimpleNamespace(id=i) for i in range(1, 4)}
    now = datetime(2026, 9, 29)
    pairs = [
        (5, "eviction", [items[1]]),  # no snapshot, but failed last time
        (6, "eviction", [items[2]]),  # fresh, nothing new
    ]
    snaps = {(6, "eviction"): SimpleNamespace(source_item_ids=[2], updated_at=now)}
    assert [p[0] for p in order_pairs_for_refresh(pairs, snaps)] == [6, 5]


async def test_synthesis_failure_is_remembered_and_cleared(monkeypatch):
    monkeypatch.setattr(law_synthesizer, "_failed_last_attempt", set())
    _patch_client(monkeypatch, law_synthesizer, _reply("{}", stop_reason="refusal"))
    with pytest.raises(EnrichmentParseError):
        await law_synthesizer.synthesize_law_snapshot(_synth_session(), 9, "eviction", [_item(1)])
    assert (9, "eviction") in law_synthesizer._failed_last_attempt

    _patch_client(monkeypatch, law_synthesizer, _reply(
        {"headline": "h", "summary": "s", "key_facts": [], "statutory_references": [],
         "confidence": "med", "caveats": ""}))
    await law_synthesizer.synthesize_law_snapshot(_synth_session(), 9, "eviction", [_item(1)])
    assert (9, "eviction") not in law_synthesizer._failed_last_attempt


async def test_refresh_laws_uses_the_same_pair_selection(monkeypatch):
    from api import main

    class _Ctx:
        async def __aenter__(self):
            return _synth_session()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(main, "async_session", lambda: _Ctx())
    pairs = [(1, "eviction", [_item(1)]), (2, "eviction", [_item(2)])]
    monkeypatch.setattr(law_synthesizer, "find_jurisdiction_topic_pairs_with_items",
                        AsyncMock(return_value=pairs))
    chosen = AsyncMock(return_value=[pairs[1]])
    monkeypatch.setattr(law_synthesizer, "select_pairs_for_refresh", chosen)
    synth = AsyncMock(return_value=None)
    monkeypatch.setattr(law_synthesizer, "synthesize_law_snapshot", synth)

    await main._run_refresh_laws_task(min_items=1, max_pairs=1)

    assert chosen.await_args.args[1:] == (pairs, 1)
    assert [c.args[1] for c in synth.await_args_list] == [2]


@pytest.mark.parametrize("module, call", [
    (law_synthesizer, lambda: law_synthesizer.synthesize_law_snapshot(
        _synth_session(), 1, "eviction", [_item(1)])),
    (content_drafter, lambda: content_drafter.generate_blog_draft(
        _synth_session(), SimpleNamespace(id=3, title="t", summary="s", impact_score="high",
                                          impact_reasoning="r", topic_tags=[], action_needed=None,
                                          source_url=None))),
])
async def test_opus_calls_get_a_600_second_timeout(monkeypatch, module, call):
    create = _patch_client(monkeypatch, module, _reply(
        {"headline": "h", "summary": "s", "key_facts": [], "statutory_references": [],
         "confidence": "med", "caveats": "", "title": "T", "body": "B"}))
    await call()
    assert create.await_args.kwargs["timeout"] == 600
