"""add_calendar_connection_table

Revision ID: 9209b8ea610c
Revises: fe9a3ef4cecc
Create Date: 2026-07-09 16:57:05.542573

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9209b8ea610c'
down_revision: Union[str, Sequence[str], None] = 'fe9a3ef4cecc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "calendar_connection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cached_ics", sa.Text(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_calendar_connection_id"), "calendar_connection", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_connection_profile_id"),
        "calendar_connection",
        ["profile_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_calendar_connection_profile_id"), table_name="calendar_connection"
    )
    op.drop_index(op.f("ix_calendar_connection_id"), table_name="calendar_connection")
    op.drop_table("calendar_connection")
