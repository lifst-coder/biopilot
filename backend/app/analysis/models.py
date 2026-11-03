"""ORM model for stored analysis results (immutable; re-runs create new rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow
from app.core.immutability import ImmutableMixin


class AnalysisResult(ImmutableMixin, Base):
    """Output of one deterministic computation over one or more datasets.

    ``input_fingerprint`` = sha256(method_version + dataset sha256s + parameters) so
    identical inputs are never recomputed into duplicate rows.
    """

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("eln_experiments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    method_version: Mapped[str] = mapped_column(String(32))
    input_dataset_ids: Mapped[list[int]] = mapped_column(JSON)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    output: Mapped[dict[str, Any]] = mapped_column(JSON)
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
