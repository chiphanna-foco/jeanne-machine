"""Startup schema migrations: one failing step must not skip the rest."""

from contextlib import contextmanager

import api.main as main


class _FakeConn:
    def __init__(self, log, fail_on):
        self.log, self.fail_on = log, fail_on

    def execute(self, stmt):
        sql = str(stmt)
        if "lock_timeout" not in sql and any(f in sql for f in self.fail_on):
            raise RuntimeError(f"boom: {sql[:40]}")
        self.log.append(sql)


class _FakeEngine:
    def __init__(self, fail_on=()):
        self.log, self.fail_on = [], fail_on

    @contextmanager
    def begin(self):
        yield _FakeConn(self.log, self.fail_on)

    def dispose(self):
        pass


def _run(monkeypatch, engine):
    monkeypatch.setattr(main, "create_engine", lambda url: engine)
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda eng: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return main.run_schema_migrations()


def test_all_steps_ok(monkeypatch):
    engine = _FakeEngine()
    status = _run(monkeypatch, engine)
    assert status["ok"] is True
    assert any("parse_failures" in sql for sql in engine.log)
    assert main._migration_status is status


def test_failed_step_does_not_skip_later_columns(monkeypatch):
    # The 2026-10-06 outage: an early failure skipped the parse_failures column.
    engine = _FakeEngine(fail_on=("classified_at = COALESCE",))
    status = _run(monkeypatch, engine)
    assert status["ok"] is False
    failed = [s["step"] for s in status["steps"] if not s["ok"]]
    assert failed == ["raw_document.classified_at backfill"]
    assert any("parse_failures" in sql for sql in engine.log)


def test_missing_vector_extension_alone_is_not_a_schema_failure(monkeypatch):
    status = _run(monkeypatch, _FakeEngine(fail_on=("CREATE EXTENSION",)))
    assert status["ok"] is True
    assert status["steps"][0] == {"step": "vector extension", "ok": False, "error": status["steps"][0]["error"]}


def test_engine_failure_is_reported_not_raised(monkeypatch):
    def boom(url):
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr(main, "create_engine", boom)
    status = main.run_schema_migrations()
    assert status["ok"] is False
    assert "psycopg" in status["steps"][0]["error"]


def test_sync_url_names_an_installed_driver():
    # SQLAlchemy 2.1 maps bare postgresql:// to psycopg (v3), not installed here.
    from sqlalchemy import create_engine

    from config import Settings

    for raw in ("postgres://u:p@h/d", "postgresql://u:p@h/d", "postgresql+asyncpg://u:p@h/d"):
        url = Settings(database_url=raw).sync_database_url
        assert url == "postgresql+psycopg2://u:p@h/d"
        create_engine(url).dispose()  # raises if the driver module is missing
