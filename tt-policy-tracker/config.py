"""Central configuration via pydantic-settings. Reads from env vars / .env file."""

import os
import re

from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    """Convert DATABASE_URL to asyncpg format for SQLAlchemy.

    Railway provides DATABASE_URL as postgresql://... but SQLAlchemy async
    needs postgresql+asyncpg://...  Also handles postgres:// (legacy Heroku style).
    """
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    openstates_api_key: str = ""
    congress_api_key: str = ""
    anthropic_api_key: str = ""
    postmark_token: str = ""

    # Slack — set SLACK_WEBHOOK_URL to an incoming webhook URL for Slack digests
    slack_webhook_url: str = ""

    # CourtListener — free API token from courtlistener.com
    courtlistener_api_token: str = ""

    # Open States scope — "phase0" (OH + CO only) or "all" (all 50 states)
    openstates_scope: str = "all"

    # Database — Railway sets DATABASE_URL; we normalize it for asyncpg
    database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:5432/policy_tracker"

    # S3
    s3_bucket: str = "tt-policy-tracker-raw"

    # Digest
    digest_recipient: str = "chip.hanna@gmail.com"
    digest_from_email: str = "policy-tracker@turbotenant.com"

    # AI models
    classifier_model: str = "claude-haiku-4-5-20251001"
    summarizer_model: str = "claude-sonnet-4-6"

    # Enrichment thresholds
    relevance_confidence_threshold: float = 0.6

    # Server
    port: int = 8000

    # CORS — set CORS_ORIGINS to a comma-separated list of allowed origins
    cors_origins: str = "http://localhost:3000"

    # Admin token for triggering pipelines via the API (set a random string)
    admin_token: str = ""

    @property
    def async_database_url(self) -> str:
        return _normalize_database_url(self.database_url)

    @property
    def sync_database_url(self) -> str:
        """For Alembic and table creation (sync driver)."""
        url = self.database_url
        url = re.sub(r"^postgres(ql)?(\+asyncpg)?://", "postgresql://", url)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
