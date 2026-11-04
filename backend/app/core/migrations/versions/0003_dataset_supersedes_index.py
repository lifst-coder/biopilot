"""eln: index datasets by supersedes_dataset_id

Every ``DatasetOut`` carries ``superseded_by_dataset_id``, read as
``SELECT id FROM eln_datasets WHERE supersedes_dataset_id = :id``. Without an index that
is a full scan of the dataset table per dataset (PERFORMANCE.md, recall/FTS/knowledge
graph). Index only — no data changes.

Revision ID: 0003_dataset_supersedes_index
Revises: 0002_decision_decided_on
Create Date: 2026-11-04 00:32:28.019982
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_dataset_supersedes_index"
down_revision: str | None = "0002_decision_decided_on"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``ix_eln_datasets_supersedes_dataset_id``."""
    with op.batch_alter_table("eln_datasets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_eln_datasets_supersedes_dataset_id"),
            ["supersedes_dataset_id"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the index."""
    with op.batch_alter_table("eln_datasets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eln_datasets_supersedes_dataset_id"))
