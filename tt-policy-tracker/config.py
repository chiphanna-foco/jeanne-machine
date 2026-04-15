"""Central configuration via pydantic-settings. Reads from env vars / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    openstates_api_key: str = ""
    congress_api_key: str = ""
    anthropic_api_key: str = ""
    postmark_token: str = ""

    # Database
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


settings = Settings()
