"""Tests for config URL normalization (Railway/Heroku compatibility)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import _normalize_database_url


def test_postgresql_passthrough():
    url = "postgresql+asyncpg://user:pass@host:5432/db"
    assert _normalize_database_url(url) == url


def test_postgres_scheme_converted():
    url = "postgres://user:pass@host:5432/db"
    assert _normalize_database_url(url) == "postgresql+asyncpg://user:pass@host:5432/db"


def test_postgresql_without_asyncpg_converted():
    url = "postgresql://user:pass@host:5432/db"
    assert _normalize_database_url(url) == "postgresql+asyncpg://user:pass@host:5432/db"


def test_railway_style_url():
    url = "postgresql://tracker:abc123@roundhouse.proxy.rlwy.net:5432/railway"
    result = _normalize_database_url(url)
    assert result == "postgresql+asyncpg://tracker:abc123@roundhouse.proxy.rlwy.net:5432/railway"
