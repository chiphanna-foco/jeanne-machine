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
