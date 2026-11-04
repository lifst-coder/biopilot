"""eln: protocol steps, paste source, runs

Protocol templates gain ``version_label`` ("v1.1"), executable ``steps``, the pasted
original ``source_text`` and the reviewed ``extraction``. New append-only run tables:
``eln_protocol_runs`` (one bench execution) and ``eln_protocol_run_entries`` (checks,
actual values, notes). Existing templates keep empty defaults (steps derived from note).

Revision ID: 0004_protocol_runs
Revises: 0003_dataset_supersedes_index
Create Date: 2026-11-04 03:57:10.286635
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_protocol_runs"
down_revision: str | None = "0003_dataset_supersedes_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "eln_protocol_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("protocol_template_id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["eln_experiments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["eln_projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["protocol_template_id"],
            ["eln_protocol_templates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("eln_protocol_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_eln_protocol_runs_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_eln_protocol_runs_protocol_template_id"),
            ["protocol_template_id"],
            unique=False,
        )

    op.create_table(
        "eln_protocol_run_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eln_protocol_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_protocol_run_entry"),
    )
    with op.batch_alter_table("eln_protocol_run_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_eln_protocol_run_entries_run_id"), ["run_id"], unique=False
        )

    with op.batch_alter_table("eln_protocol_templates", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("version_label", sa.String(length=20), server_default="", nullable=False)
        )
        batch_op.add_column(sa.Column("steps", sa.JSON(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("source_text", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("extraction", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Revert this revision."""
    with op.batch_alter_table("eln_protocol_templates", schema=None) as batch_op:
        batch_op.drop_column("extraction")
        batch_op.drop_column("source_text")
        batch_op.drop_column("steps")
        batch_op.drop_column("version_label")

    with op.batch_alter_table("eln_protocol_run_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eln_protocol_run_entries_run_id"))

    op.drop_table("eln_protocol_run_entries")
    with op.batch_alter_table("eln_protocol_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eln_protocol_runs_protocol_template_id"))
        batch_op.drop_index(batch_op.f("ix_eln_protocol_runs_project_id"))

    op.drop_table("eln_protocol_runs")
