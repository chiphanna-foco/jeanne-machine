"""Initial schema — all tables from §5.3 of the build plan.

Revision ID: 001
Revises: None
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "jurisdiction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "level",
            sa.Enum("federal", "state", "county", "city", "court", name="jurisdiction_level"),
            nullable=False,
        ),
        sa.Column("state_code", sa.Text()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("fips_code", sa.Text()),
        sa.Column("lat", sa.Float()),
        sa.Column("lng", sa.Float()),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("jurisdiction.id")),
    )

    op.create_table(
        "source_adapter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), default=True),
    )

    op.create_table(
        "raw_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_adapter_id", sa.Integer(), sa.ForeignKey("source_adapter.id"), nullable=False),
        sa.Column("jurisdiction_id", sa.Integer(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("raw_s3_key", sa.Text()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("content_hash", sa.Text()),
        sa.Column("raw_text", sa.Text()),
    )

    op.create_table(
        "policy_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_document_id", sa.Integer(), sa.ForeignKey("raw_document.id"), nullable=False, unique=True),
        sa.Column("jurisdiction_id", sa.Integer(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("full_text", sa.Text()),
        sa.Column("impact_score", sa.Enum("low", "med", "high", name="impact_score"), nullable=False),
        sa.Column("impact_reasoning", sa.Text()),
        sa.Column("action_needed", sa.Enum("inform", "monitor", "urgent", name="action_needed")),
        sa.Column("effective_date", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source_url", sa.Text()),
        sa.Column("topic_tags", sa.ARRAY(sa.Text())),
        sa.Column("embedding", sa.Text()),  # pgvector column added via raw SQL below
    )

    # Replace the text column with a proper vector column
    op.execute("ALTER TABLE policy_item DROP COLUMN embedding")
    op.execute("ALTER TABLE policy_item ADD COLUMN embedding vector(1536)")

    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Enum("daily", "weekly", name="digest_frequency"), nullable=False),
        sa.Column("jurisdictions", sa.ARRAY(sa.Integer())),
        sa.Column("topics", sa.ARRAY(sa.Text())),
        sa.Column("keywords", sa.ARRAY(sa.Text())),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "digest_send",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscription.id"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("item_ids", sa.ARRAY(sa.Integer())),
        sa.Column("message_id", sa.Text()),
    )

    # Create indexes for common queries
    op.create_index("ix_policy_item_discovered_at", "policy_item", ["discovered_at"])
    op.create_index("ix_policy_item_impact_score", "policy_item", ["impact_score"])
    op.create_index("ix_raw_document_content_hash", "raw_document", ["content_hash"])
    op.create_index("ix_raw_document_external_id", "raw_document", ["external_id"])


def downgrade() -> None:
    op.drop_table("digest_send")
    op.drop_table("subscription")
    op.drop_table("policy_item")
    op.drop_table("raw_document")
    op.drop_table("source_adapter")
    op.drop_table("jurisdiction")

    op.execute("DROP TYPE IF EXISTS jurisdiction_level")
    op.execute("DROP TYPE IF EXISTS impact_score")
    op.execute("DROP TYPE IF EXISTS action_needed")
    op.execute("DROP TYPE IF EXISTS digest_frequency")
