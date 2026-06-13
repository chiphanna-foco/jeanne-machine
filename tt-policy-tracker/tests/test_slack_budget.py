"""Tests for the weekly Slack digest post budget.

The product rule (TurboTenant, 2026-06-13): at most N digest posts per ISO
week, enforced durably so no combination of crons can exceed it. These tests
drive send_digest_within_budget with a fake session (the real one needs
Postgres) so the gate decision and the ledger write are both covered.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import digest.slack as slackmod
from digest.slack import send_digest_within_budget


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeSession:
    """Minimal async session stand-in: returns a fixed week-count, records adds."""

    def __init__(self, week_count: int):
        self._week_count = week_count
        self.added: list = []
        self.committed = False

    async def execute(self, _query):
        return _ScalarResult(self._week_count)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def _stub_send(monkeypatch, ok: bool = True):
    calls = []

    async def fake_send(url, blocks, fallback_text="x"):
        calls.append((url, blocks, fallback_text))
        return ok

    monkeypatch.setattr(slackmod, "send_to_slack", fake_send)
    return calls


async def test_blocks_when_budget_already_spent(monkeypatch):
    calls = _stub_send(monkeypatch)
    session = FakeSession(week_count=2)

    sent, reason = await send_digest_within_budget(
        session, "http://hook", [{"x": 1}], "fallback", budget=2
    )

    assert sent is False
    assert "budget" in reason
    assert calls == []  # never even hit the webhook
    assert session.added == []
    assert session.committed is False


async def test_sends_and_records_when_under_budget(monkeypatch):
    calls = _stub_send(monkeypatch, ok=True)
    session = FakeSession(week_count=1)

    sent, reason = await send_digest_within_budget(
        session, "http://hook", [{"x": 1}], "fallback", budget=2, item_count=7
    )

    assert sent is True
    assert "2/2" in reason
    assert len(calls) == 1
    assert len(session.added) == 1
    post = session.added[0]
    assert post.kind == "digest"
    assert post.item_count == 7
    assert session.committed is True


async def test_first_post_of_week_allowed(monkeypatch):
    _stub_send(monkeypatch, ok=True)
    session = FakeSession(week_count=0)
    sent, reason = await send_digest_within_budget(
        session, "http://hook", [], "fallback", budget=2
    )
    assert sent is True
    assert "1/2" in reason


async def test_no_ledger_write_when_send_fails(monkeypatch):
    _stub_send(monkeypatch, ok=False)
    session = FakeSession(week_count=0)

    sent, reason = await send_digest_within_budget(
        session, "http://hook", [], "fallback", budget=2
    )

    assert sent is False
    assert reason == "Slack webhook send failed"
    assert session.added == []  # a failed send must not consume the budget
    assert session.committed is False


async def test_iso_week_stamp_uses_now(monkeypatch):
    _stub_send(monkeypatch, ok=True)
    session = FakeSession(week_count=0)
    now = datetime(2026, 1, 1)  # ISO week 1 of 2026
    iso_year, iso_week, _ = now.isocalendar()

    await send_digest_within_budget(
        session, "http://hook", [], "fallback", budget=2, now=now
    )

    post = session.added[0]
    assert post.iso_year == iso_year
    assert post.iso_week == iso_week
