"""SQLAlchemy models per §5.3 of the build plan."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Jurisdiction(Base):
    __tablename__ = "jurisdiction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(
        Enum("federal", "state", "county", "city", "court", name="jurisdiction_level"),
        nullable=False,
    )
    state_code: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fips_code: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdiction.id"))

    parent: Mapped["Jurisdiction | None"] = relationship("Jurisdiction", remote_side=[id])
    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="jurisdiction")
    policy_items: Mapped[list["PolicyItem"]] = relationship(back_populates="jurisdiction")


class SourceAdapter(Base):
    __tablename__ = "source_adapter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="source_adapter")


class RawDocument(Base):
    __tablename__ = "raw_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_adapter_id: Mapped[int] = mapped_column(ForeignKey("source_adapter.id"), nullable=False)
    jurisdiction_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdiction.id"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    raw_s3_key: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set by enrichment.pipeline.enrich_document after the classifier runs,
    # regardless of verdict. Used to exclude already-classified docs from
    # the enrichment queue so rejected docs don't get re-processed forever.
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)

    source_adapter: Mapped["SourceAdapter"] = relationship(back_populates="raw_documents")
    jurisdiction: Mapped["Jurisdiction | None"] = relationship(back_populates="raw_documents")
    policy_item: Mapped["PolicyItem | None"] = relationship(back_populates="raw_document")


class PolicyItem(Base):
    __tablename__ = "policy_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_document.id"), nullable=False, unique=True
    )
    jurisdiction_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdiction.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    full_text: Mapped[str | None] = mapped_column(Text)
    impact_score: Mapped[str] = mapped_column(
        Enum("low", "med", "high", name="impact_score"), nullable=False
    )
    impact_reasoning: Mapped[str | None] = mapped_column(Text)
    action_needed: Mapped[str | None] = mapped_column(
        Enum("inform", "monitor", "urgent", name="action_needed")
    )
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when we've sent a Slack alert about this item's upcoming
    # effective_date, so we don't re-alert on every daily cron pass.
    effective_alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    topic_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    embedding = mapped_column(Vector(1536), nullable=True)

    raw_document: Mapped["RawDocument"] = relationship(back_populates="policy_item")
    jurisdiction: Mapped["Jurisdiction | None"] = relationship(back_populates="policy_items")


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(
        Enum("daily", "weekly", name="digest_frequency"), nullable=False
    )
    jurisdictions: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DigestSend(Base):
    __tablename__ = "digest_send"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscription.id"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    item_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    message_id: Mapped[str | None] = mapped_column(Text)

    subscription: Mapped["Subscription"] = relationship()


class LawSnapshot(Base):
    """Per-jurisdiction, per-topic summary of the current state of law.

    Built by synthesizing all relevant PolicyItems for a (jurisdiction, topic)
    pair using AI. Refreshed weekly when new policy activity is detected.
    """

    __tablename__ = "law_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(
        ForeignKey("jurisdiction.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)

    # AI-synthesized narrative describing the current state of law
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Short headline for the topic (e.g. "Security deposits capped at 1 month's rent")
    headline: Mapped[str | None] = mapped_column(Text)

    # Key facts as structured list (bullets)
    key_facts: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # Statutory/regulatory references mentioned in source items
    statutory_references: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # The policy_item ids that fed into this synthesis
    source_item_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))

    # How confident the AI is that this accurately reflects current law
    # ("high" = multiple sources agree, "med" = single strong source,
    #  "low" = limited or conflicting information)
    confidence: Mapped[str] = mapped_column(
        Enum("low", "med", "high", name="law_confidence"), default="med"
    )

    # Warning text (e.g. "Based on recent activity only; does not reflect full statutory history")
    caveats: Mapped[str | None] = mapped_column(Text)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    jurisdiction: Mapped["Jurisdiction"] = relationship()


class ContentDraft(Base):
    """AI-generated draft blog post or social content from a high-impact PolicyItem."""

    __tablename__ = "content_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_item_id: Mapped[int] = mapped_column(
        ForeignKey("policy_item.id"), nullable=False, unique=True
    )
    content_type: Mapped[str] = mapped_column(
        Enum("blog_post", "social_post", "newsletter_blurb", name="content_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    seo_description: Mapped[str | None] = mapped_column(Text)
    suggested_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(
        Enum("draft", "approved", "rejected", "published", name="draft_status"),
        default="draft",
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    policy_item: Mapped["PolicyItem"] = relationship()


class CpiReading(Base):
    """A single CPI-U index reading from BLS, used to drive rent-cap math.

    California (AB 1482) and Oregon (SB 608/611) cap allowable rent increases
    at a fixed percentage plus the regional CPI change. We store the raw BLS
    index values here so the rent caps can be recomputed and Autopilot can
    read structured numbers.
    """

    __tablename__ = "cpi_reading"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    area_name: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # BLS period code: M01-M12 monthly, M13 = annual average
    period: Mapped[str] = mapped_column(Text, nullable=False)
    period_name: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float] = mapped_column(nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ItemFeedback(Base):
    """A 👍 / 👎 / 👀 signal on a tracked bill.

    Append-only (one row per click) so the history is auditable, like the
    TT-LLM signal_layer feedback log. The latest row per ``bill_key`` wins.

    Keyed on ``bill_key`` — the canonical, source-independent bill identity
    (e.g. ``CO:HB1045:2026`` from enrichment.triage.canonical_bill_key) — NOT
    on policy_item.id. policy_item.id changes every time a bill is
    re-classified (new raw doc → new PolicyItem row), so id-keyed feedback
    would orphan itself on the next pipeline run. bill_key is stable across
    re-runs, so a thumbs-down stays suppressed. item_id is kept only for
    reference/debugging.
    """

    __tablename__ = "item_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # 'up' (relevant/useful) | 'down' (noise — suppress) | 'watching'
    label: Mapped[str] = mapped_column(
        Enum("up", "down", "watching", name="feedback_label"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    item_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SlackPost(Base):
    """Ledger of automated digest Slack posts — enforces the weekly post budget.

    The product rule (TurboTenant, 2026-06-13): at most N digest posts per ISO
    week (``settings.slack_weekly_post_budget``, default 2). One row per post.
    Durable so the cap survives container restarts and holds across every path
    that posts (twice-weekly digest cron, weekly-full pipeline, manual trigger).

    ``iso_year``/``iso_week`` are stored denormalized so "how many this week"
    is a trivial indexed count with no date math or timezone edge cases.
    """

    __tablename__ = "slack_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # What kind of post this was. Only "digest" is budget-governed today; the
    # column lets us add other categories (e.g. ops acks) without a migration.
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="digest")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

