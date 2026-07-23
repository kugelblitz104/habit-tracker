"""add profile.insights_enabled

Revision ID: d5f2a9c7b1e4
Revises: a3d1e5f7c9b2
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5f2a9c7b1e4"
down_revision: Union[str, Sequence[str], None] = "a3d1e5f7c9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-profile toggle for the Insights page (default on, matching the other
    # page flags). Existing profiles get it enabled via the server default.
    op.add_column(
        "profile",
        sa.Column(
            "insights_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("profile", "insights_enabled")
