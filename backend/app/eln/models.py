"""ORM models for the ELN layer. Original records are immutable (see CLAUDE.md §2).

Corrections never edit an original: they are new rows (addenda, metadata revisions,
re-uploaded datasets, new template versions), each with an audit event.
"""

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
        "cloned_from_experiment_id",
        "protocol_template_id",
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
    cloned_from_experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )
    #: Plain id (no FK) to avoid a circular FK with ``eln_protocol_templates``.
    protocol_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRevision(ImmutableMixin, Base):
    """One metadata correction (title/author) with before/after values (ELN-3)."""

    __tablename__ = "eln_experiment_revisions"
    __table_args__ = (UniqueConstraint("experiment_id", "revision", name="uq_experiment_rev"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentAddendum(ImmutableMixin, Base):
    """Supplementary note added after the fact; the original note stays untouched (ELN-2)."""

    __tablename__ = "eln_experiment_addenda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    note: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttachmentFile(ImmutableMixin, Base):
    """Binary attachment stored on disk under its sha256 (ELN-4). No delete route."""

    __tablename__ = "eln_attachment_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    description: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
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
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    source_encoding: Mapped[str] = mapped_column(String(16), default="utf-8")
    # Indexed: every DatasetOut looks up its successor by this column.
    supersedes_dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_datasets.id"), nullable=True, index=True
    )
    source_attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_attachment_files.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConditionTemplate(ImmutableMixin, Base):
    """Versioned per-project condition-block template (ELN-5). New version = new row."""

    __tablename__ = "eln_condition_templates"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_condition_template"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProtocolTemplate(ImmutableMixin, Base):
    """Reusable protocol (note skeleton + conditions). Same name again → next version."""

    __tablename__ = "eln_protocol_templates"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version", name="uq_protocol_template"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    raw_note_template: Mapped[str] = mapped_column(Text, default="")
    condition_block: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )
    author: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: Researcher-facing version name ("v1.1"); empty → ``v<version>``.
    version_label: Mapped[str] = mapped_column(String(20), default="", server_default="")
    #: Executable steps ``[{title, detail, condition_keys}]``; empty → derived from the note.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    #: Pasted original text the template was confirmed from (original record).
    source_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: Extraction provenance (:class:`app.eln.schemas.ExtractionReview`), if pasted.
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ProtocolRun(ImmutableMixin, Base):
    """One execution of a protocol template at the bench.

    Only ``status``, ``completed_at`` and ``experiment_id`` change (once, on completion,
    with an audit event); progress itself is the append-only :class:`ProtocolRunEntry`.
    """

    __tablename__ = "eln_protocol_runs"
    __immutable_fields__: ClassVar[tuple[str, ...]] = (
        "project_id",
        "protocol_template_id",
        "operator",
        "started_at",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("eln_projects.id"), index=True)
    protocol_template_id: Mapped[int] = mapped_column(
        ForeignKey("eln_protocol_templates.id"), index=True
    )
    operator: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("eln_experiments.id"), nullable=True
    )


class ProtocolRunEntry(ImmutableMixin, Base):
    """One immutable step check/uncheck, actual value or note recorded during a run."""

    __tablename__ = "eln_protocol_run_entries"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_protocol_run_entry"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eln_protocol_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    step_index: Mapped[int] = mapped_column(Integer)
    key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
