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
    # Max act-now items per Slack alert; overflow is summarized in one footer
    # line and lives in the dashboard. Keeps a backfill from blasting 50 states
    # at once at the legal team.
    slack_max_alert_items: int = 8
    # Hard cap on automated DIGEST posts per ISO week, enforced durably via the
    # slack_post ledger (digest.slack.send_digest_within_budget). The product
    # rule (TurboTenant, 2026-06-13): at most 2 Slack posts a week — anything
    # beyond is noise. Every cron path and manual digest trigger shares this
    # budget, so they can't collectively exceed it.
    slack_weekly_post_budget: int = 2
    # Real-time per-sweep "act now" Slack pings. OFF by default: the 2-hourly
    # search sweep and daily pipeline would otherwise ping on every newly-
    # discovered enacted law (the national-search backfill makes that ~13/day).
    # Items are still ingested/enriched/tracked; the twice-weekly digest carries
    # them. Flip to true only if same-day urgent pings are wanted again.
    slack_realtime_alerts: bool = False

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

    # LegiScan full-text SEARCH discovery (recall-first primary path).
    # Comma-separated standing queries run nationally (state=ALL) each sweep;
    # empty string = use the defaults in adapters/legiscan_search.py.
    legiscan_search_queries: str = ""
    # Drop search hits below this LegiScan relevance score (0-100).
    legiscan_search_min_relevance: int = 50
    # Per-run cap on getBill detail fetches; overflow is logged and picked up
    # next run (its change_hash stays unseen).
    legiscan_search_max_getbill: int = 300
    # Self-imposed monthly query ceiling (defensive backstop). LegiScan's free
    # key allows 30,000/calendar-month and SUSPENDS the account on overage (and
    # forbids extra keys), so we stop well under it. Counts every LegiScan op
    # across both adapters in the api_usage table; resets each calendar month.
    legiscan_monthly_budget: int = 27000

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

    @property
    def legiscan_search_queries_list(self) -> list[str]:
        """Standing search queries; falls back to the adapter's default set."""
        custom = [q.strip() for q in self.legiscan_search_queries.split(",") if q.strip()]
        if custom:
            return custom
        from adapters.legiscan_search import DEFAULT_QUERIES

        return list(DEFAULT_QUERIES)


settings = Settings()
