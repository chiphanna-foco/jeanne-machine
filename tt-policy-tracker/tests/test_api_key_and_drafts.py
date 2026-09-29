"""X-Jeanne-Key guard on /api/* and the per-item blog-draft endpoints.

The TestClient is created WITHOUT a `with` block so the app lifespan (which
connects to Postgres) never runs. The DB helpers in api.routes_items_drafts
are replaced with an in-memory store, because the models need pgvector and
no test database is wired up for this suite.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

import api.routes_items_drafts as rid
from api.main import app
from storage.database import get_session

KEY = "test-key-not-a-secret"


class FakeStore:
    def __init__(self):
        self.items = {7: SimpleNamespace(id=7, title="Test bill")}
        self.drafts: list[SimpleNamespace] = []
        self.drafter_calls = 0


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()

    async def fake_session():
        yield None

    async def get_item(_session, item_id):
        return s.items.get(item_id)

    async def find_draft(_session, item_id):
        return next((d for d in s.drafts if d.policy_item_id == item_id), None)

    async def run_blog_draft(item_id):
        # Mirrors the real job: drafter creates one ContentDraft(status="draft").
        s.drafter_calls += 1
        s.drafts.append(
            SimpleNamespace(
                id=100 + len(s.drafts),
                policy_item_id=item_id,
                content_type="blog_post",
                title="Draft",
                status="draft",
                generated_at=None,
            )
        )
        rid._drafting.discard(item_id)

    monkeypatch.setattr(rid, "_get_item", get_item)
    monkeypatch.setattr(rid, "_find_draft", find_draft)
    monkeypatch.setattr(rid, "_run_blog_draft", run_blog_draft)
    rid._drafting.clear()
    rid._last_error.clear()
    app.dependency_overrides[get_session] = fake_session
    yield s
    app.dependency_overrides.pop(get_session, None)
    rid._drafting.clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JEANNE_API_KEY", KEY)
    monkeypatch.delenv("JEANNE_API_KEY_MODE", raising=False)
    return TestClient(app)


def test_api_without_key_is_401(client, store):
    r = client.get("/api/items/7/drafts")
    assert r.status_code == 401


def test_api_with_wrong_key_is_401(client, store):
    r = client.get("/api/items/7/drafts", headers={"X-Jeanne-Key": "nope"})
    assert r.status_code == 401


def test_api_with_key_is_200(client, store):
    r = client.get("/api/items/7/drafts", headers={"X-Jeanne-Key": KEY})
    assert r.status_code == 200
    assert r.json()["status"] == "none"


def test_health_is_open(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_admin_not_gated_by_key(client, monkeypatch):
    # /admin/* keeps its own ?token= check; the key guard must not touch it.
    from config import settings

    monkeypatch.setattr(settings, "admin_token", "admintok")
    r = client.get("/admin/pipeline-status?token=admintok")
    assert r.status_code == 200


def test_unset_key_fails_closed(monkeypatch, store):
    monkeypatch.delenv("JEANNE_API_KEY", raising=False)
    monkeypatch.delenv("JEANNE_API_KEY_MODE", raising=False)
    c = TestClient(app)
    assert c.get("/api/items/7/drafts").status_code == 503
    assert c.get("/api/items/7/drafts", headers={"X-Jeanne-Key": ""}).status_code == 503
    assert c.get("/health").status_code == 200


def test_unset_key_fails_closed_even_in_warn_mode(monkeypatch, store):
    monkeypatch.delenv("JEANNE_API_KEY", raising=False)
    monkeypatch.setenv("JEANNE_API_KEY_MODE", "warn")
    assert TestClient(app).get("/api/items/7/drafts").status_code == 503


def test_warn_mode_allows_keyless(monkeypatch, store):
    monkeypatch.setenv("JEANNE_API_KEY", KEY)
    monkeypatch.setenv("JEANNE_API_KEY_MODE", "warn")
    assert TestClient(app).get("/api/items/7/drafts").status_code == 200


def test_two_posts_create_exactly_one_draft(client, store):
    h = {"X-Jeanne-Key": KEY}
    r1 = client.post("/api/items/7/drafts", headers=h)
    assert r1.status_code == 202
    assert r1.json()["status"] == "drafting"
    r2 = client.post("/api/items/7/drafts", headers=h)
    assert r2.status_code == 200
    assert r2.json()["status"] == "exists"
    assert r2.json()["draft"]["id"] == store.drafts[0].id
    assert len(store.drafts) == 1
    assert store.drafts[0].status == "draft"
    assert store.drafter_calls == 1
    poll = client.get("/api/items/7/drafts", headers=h).json()
    assert poll["status"] == "exists" and poll["draft"]["id"] == store.drafts[0].id


def test_click_while_drafting_starts_no_second_job(client, store, monkeypatch):
    started = []

    async def slow_job(item_id):  # never finishes during the test
        started.append(item_id)

    monkeypatch.setattr(rid, "_run_blog_draft", slow_job)
    h = {"X-Jeanne-Key": KEY}
    assert client.post("/api/items/7/drafts", headers=h).status_code == 202
    r2 = client.post("/api/items/7/drafts", headers=h)
    assert r2.status_code == 202 and r2.json()["status"] == "drafting"
    assert started == [7]
    assert client.get("/api/items/7/drafts", headers=h).json()["status"] == "drafting"


def test_existing_social_draft_is_returned_not_duplicated(client, store):
    store.drafts.append(
        SimpleNamespace(id=55, policy_item_id=7, content_type="social_post",
                        title="s", status="draft", generated_at=None)
    )
    r = client.post("/api/items/7/drafts", headers={"X-Jeanne-Key": KEY})
    assert r.status_code == 200
    assert r.json()["draft"]["id"] == 55 and "note" in r.json()
    assert store.drafter_calls == 0


def test_unknown_item_404(client, store):
    r = client.post("/api/items/999/drafts", headers={"X-Jeanne-Key": KEY})
    assert r.status_code == 404
