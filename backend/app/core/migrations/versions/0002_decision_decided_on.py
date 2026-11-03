"""partner: decision decided_on

``partner_decisions.decided_on`` (nullable ``Date``): the day the researcher decided,
which can precede the row's ``created_at`` when a lab history is back-filled (seed lab
profile, ISSUES P1-9). Existing rows keep ``NULL`` (= decided when recorded).

Revision ID: 0002_decision_decided_on
Revises: 0001_baseline
Create Date: 2026-11-03 15:33:54.814789
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_decision_decided_on"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``decided_on`` column (batch mode for SQLite)."""
    with op.batch_alter_table("partner_decisions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decided_on", sa.Date(), nullable=True))


def downgrade() -> None:
    """Drop ``decided_on``."""
    with op.batch_alter_table("partner_decisions", schema=None) as batch_op:
        batch_op.drop_column("decided_on")
