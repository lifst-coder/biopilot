"""ORM models owned by Memory."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.immutability import ImmutableMixin


class ExperimentDigest(ImmutableMixin, Base):
    """AI-produced summary of one experiment (rules or Claude). Never edits the original."""

    __tablename__ = "memory_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    engine: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: Why the Claude draft was replaced by rules output (MEM-6); ``None`` if not replaced.
    fallback_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: sha256 over the inputs the digest was built from (MEM-8 staleness check).
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)


class KnowledgeNote(ImmutableMixin, Base):
    """Researcher-authored project knowledge linked to experiments (MEM-7). Immutable."""

    __tablename__ = "memory_knowledge_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    linked_experiment_ids: Mapped[list[int]] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexState(Base):
    """Watermark of the derived search index (last audit event indexed, per project).

    Derived bookkeeping only — not an original record, so it is mutable. Stored in the
    same transaction as the index rows so a rollback rewinds both together.
    """

    __tablename__ = "memory_index_state"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, default=0)
