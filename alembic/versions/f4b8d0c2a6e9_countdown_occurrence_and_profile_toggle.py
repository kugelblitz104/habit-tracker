"""add countdown.show_occurrence and profile.countdowns_enabled

Revision ID: f4b8d0c2a6e9
Revises: e7a2c9f1b3d8
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4b8d0c2a6e9"
down_revision: Union[str, Sequence[str], None] = "e7a2c9f1b3d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "countdown",
        sa.Column("show_occurrence", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "profile",
        sa.Column("countdowns_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("profile", "countdowns_enabled")
    op.drop_column("countdown", "show_occurrence")
