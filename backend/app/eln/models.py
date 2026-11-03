"""ORM models for the ELN layer. Original records are immutable (see CLAUDE.md §2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.immutability import ImmutableMixin


class Project(Base):
    """A research project grouping experiments toward one objective."""

    __tablename__ = "eln_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Experiment(ImmutableMixin, Base):
    """One experiment. ``raw_note``, ``condition_block`` and ``attachments`` never change."""

    __tablename__ = "eln_experiments"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_experiment_code"),)
    __immutable_fields__: ClassVar[tuple[str, ...]] = (
        "project_id",
        "code",
        "raw_note",
        "condition_block",
        "attachments",
        "performed_on",
        "parent_experiment_id",
        "created_at",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(100), default="")
    performed_on: Mapped[date] = mapped_column(Date)
    parent_experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )
    raw_note: Mapped[str] = mapped_column(Text)
    condition_block: Mapped[dict[str, Any]] = mapped_column(JSON)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dataset(ImmutableMixin, Base):
    """A CSV file attached to an experiment. Fully immutable; identified by sha256."""

    __tablename__ = "eln_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
