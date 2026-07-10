"""add time_entry table, estimated_effort, pomodoro settings

Revision ID: 44bfe95b7b50
Revises: 9ea99964c4a7
Create Date: 2026-07-10 12:38:36.766363

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44bfe95b7b50'
down_revision: Union[str, Sequence[str], None] = '9ea99964c4a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Per-profile pomodoro defaults. server_default backfills existing rows;
    # the ORM sets these Python-side on new rows.
    op.add_column(
        "profile",
        sa.Column(
            "pomodoro_work_minutes",
            sa.Integer(),
            server_default=sa.text("25"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile",
        sa.Column(
            "pomodoro_break_minutes",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile",
        sa.Column(
            "pomodoro_long_break_minutes",
            sa.Integer(),
            server_default=sa.text("15"),
            nullable=False,
        ),
    )
    op.add_column(
        "profile",
        sa.Column(
            "pomodoro_cycles",
            sa.Integer(),
            server_default=sa.text("4"),
            nullable=False,
        ),
    )

    # Estimated level of effort in minutes (est-vs-actual against time entries)
    op.add_column("task", sa.Column("estimated_effort", sa.Integer(), nullable=True))

    # Create time_entry table
    op.create_table(
        "time_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_time_entry_id"), "time_entry", ["id"], unique=False)
    op.create_index(
        op.f("ix_time_entry_profile_id"), "time_entry", ["profile_id"], unique=False
    )
    op.create_index(
        op.f("ix_time_entry_task_id"), "time_entry", ["task_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_time_entry_task_id"), table_name="time_entry")
    op.drop_index(op.f("ix_time_entry_profile_id"), table_name="time_entry")
    op.drop_index(op.f("ix_time_entry_id"), table_name="time_entry")
    op.drop_table("time_entry")

    op.drop_column("task", "estimated_effort")

    op.drop_column("profile", "pomodoro_cycles")
    op.drop_column("profile", "pomodoro_long_break_minutes")
    op.drop_column("profile", "pomodoro_break_minutes")
    op.drop_column("profile", "pomodoro_work_minutes")
