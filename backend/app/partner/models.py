"""ORM models owned by Partner. AI outputs are separate records from originals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.immutability import ImmutableMixin


class Critique(ImmutableMixin, Base):
    """One critique run over an experiment, with the evidence snapshot it used."""

    __tablename__ = "partner_critiques"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    baseline_experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )
    engine: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Hypothesis(ImmutableMixin, Base):
    """A testable statement. Only ``status`` may change (audited)."""

    __tablename__ = "partner_hypotheses"
    __immutable_fields__: ClassVar[tuple[str, ...]] = (
        "project_id",
        "experiment_id",
        "critique_id",
        "statement",
        "rationale",
        "origin",
        "evidence_keys",
        "created_at",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )
    critique_id: Mapped[int | None] = mapped_column(
        ForeignKey("partner_critiques.id"), nullable=True
    )
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    origin: Mapped[str] = mapped_column(String(16))
    evidence_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Proposal(ImmutableMixin, Base):
    """A suggested next experiment. Only ``status`` changes, via a :class:`Decision`."""

    __tablename__ = "partner_proposals"
    __immutable_fields__: ClassVar[tuple[str, ...]] = (
        "project_id",
        "experiment_id",
        "critique_id",
        "hypothesis_id",
        "title",
        "description",
        "changes",
        "evidence_keys",
        "origin",
        "created_at",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    critique_id: Mapped[int | None] = mapped_column(
        ForeignKey("partner_critiques.id"), nullable=True
    )
    hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("partner_hypotheses.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    origin: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Decision(ImmutableMixin, Base):
    """Researcher's accept/modify/reject decision with rationale (fully immutable)."""

    __tablename__ = "partner_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("partner_proposals.id"), index=True, unique=True
    )
    action: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    modifications: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decided_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
