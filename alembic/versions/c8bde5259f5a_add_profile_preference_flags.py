"""add_profile_preference_flags

Revision ID: c8bde5259f5a
Revises: 9209b8ea610c
Create Date: 2026-07-09 21:09:58.568180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8bde5259f5a'
down_revision: Union[str, Sequence[str], None] = '9209b8ea610c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "profile",
        sa.Column(
            "week_start_monday",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile",
        sa.Column(
            "use_habit_color_accent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("profile", "use_habit_color_accent")
    op.drop_column("profile", "week_start_monday")
