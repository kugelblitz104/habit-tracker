"""add countdown table

Revision ID: e7a2c9f1b3d8
Revises: b2c5e9d1a4f7
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a2c9f1b3d8"
down_revision: Union[str, Sequence[str], None] = "b2c5e9d1a4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "countdown",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_time", sa.Time(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("repeat", sa.String(), server_default="none", nullable=False),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_countdown_id"), "countdown", ["id"], unique=False)
    op.create_index(
        op.f("ix_countdown_profile_id"), "countdown", ["profile_id"], unique=False
    )
    op.create_index(
        op.f("ix_countdown_task_id"), "countdown", ["task_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_countdown_task_id"), table_name="countdown")
    op.drop_index(op.f("ix_countdown_profile_id"), table_name="countdown")
    op.drop_index(op.f("ix_countdown_id"), table_name="countdown")
    op.drop_table("countdown")
