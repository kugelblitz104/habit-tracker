"""add the three Profile.reconciliation_* windows

Revision ID: 2f964162ecc8
Revises: 18e1688678a2
Create Date: 2026-09-16 13:27:07.595420

All three nullable with no server default, so no backfill: null already means
"use the client's default", and every existing profile keeps today's behaviour.
Downgrade drops them and with them any per-profile threshold customisation.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2f964162ecc8"
down_revision: Union[str, Sequence[str], None] = "18e1688678a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "profile",
        sa.Column("reconciliation_stale_task_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "profile",
        sa.Column("reconciliation_stale_project_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "profile",
        sa.Column("reconciliation_stale_habit_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("profile", "reconciliation_stale_habit_days")
    op.drop_column("profile", "reconciliation_stale_project_days")
    op.drop_column("profile", "reconciliation_stale_task_days")
