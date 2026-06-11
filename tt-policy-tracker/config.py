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

    # BLS — optional registration key from data.bls.gov (raises daily query
    # limit from 25 to 500). Works without a key at the lower limit.
    bls_api_key: str = ""

    # LegiScan — free public API key from legiscan.com/legiscan (30,000
    # queries/month, ~4x Open States' 250/day). Covers all 50 states + DC +
    # Congress via one key. Used as the coverage-gap backstop for states whose
    # bills don't surface through Open States (e.g. Colorado / HB26-1196) and,
    # longer-term, as the primary low-quota multi-state source.
    legiscan_api_key: str = ""
    # Two-letter states pulled directly from LegiScan each run, comma-separated.
    # These are EXCLUDED from the Open States sweep to avoid double-ingesting.
    # Starts with the documented Open States gap (CO); expand as gaps are found.
    legiscan_states: str = "CO"

    # Open States scope — "phase0" (OH + CO only) or "all" (all 50 states)
    openstates_scope: str = "all"

    # Open States free tier caps at 250 requests/DAY (separate from the ~10/min
    # limit). The daily 50-state sweep would blow that, so we (a) stop before a
    # budget and (b) rotate states across days. Leave headroom below 250 for
    # manual backfills / probes.
    openstates_daily_request_budget: int = 220
    # Daily sweep rotates ALL_STATES across this many buckets — ~10 states/day
    # on a 5-day cycle keeps each run well under the daily budget.
    openstates_rotation_buckets: int = 5
    # Each rotated state is fetched with this lookback so the 5-day cycle has
    # generous overlap and a state down for a few days still catches up.
    openstates_rotation_window_days: int = 14

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

    @property
    def legiscan_states_list(self) -> list[str]:
        """Lowercase two-letter states LegiScan handles directly (gap states)."""
        return [s.strip().lower() for s in self.legiscan_states.split(",") if s.strip()]


settings = Settings()
