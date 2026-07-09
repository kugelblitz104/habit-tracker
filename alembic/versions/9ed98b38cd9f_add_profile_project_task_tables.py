"""add_profile_project_task_tables

Revision ID: 9ed98b38cd9f
Revises: f98b7e66fdfd
Create Date: 2026-07-08 23:18:48.198678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ed98b38cd9f'
down_revision: Union[str, Sequence[str], None] = 'f98b7e66fdfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create profile table
    op.create_table(
        "profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color_start", sa.String(), nullable=False),
        sa.Column("color_end", sa.String(), nullable=False),
        sa.Column("habits_enabled", sa.Boolean(), nullable=False),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False),
        sa.Column("publish_to_azure", sa.Boolean(), nullable=False),
        sa.Column("default_landing", sa.String(), nullable=False),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uix_profile_user_name"),
    )
    op.create_index(op.f("ix_profile_id"), "profile", ["id"], unique=False)
    op.create_index(op.f("ix_profile_user_id"), "profile", ["user_id"], unique=False)

    # Create project table
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_id"), "project", ["id"], unique=False)
    op.create_index(
        op.f("ix_project_profile_id"), "project", ["profile_id"], unique=False
    )

    # Create task table
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_time", sa.Time(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("block_reason", sa.String(), nullable=True),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("closed_date", sa.DateTime(), nullable=True),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_id"), "task", ["id"], unique=False)
    op.create_index(op.f("ix_task_profile_id"), "task", ["profile_id"], unique=False)
    op.create_index(op.f("ix_task_project_id"), "task", ["project_id"], unique=False)

    # Add new habit columns - profile_id starts nullable so it can be backfilled
    op.add_column("habit", sa.Column("profile_id", sa.Integer(), nullable=True))
    op.add_column("habit", sa.Column("category", sa.String(), nullable=True))

    # Data migration:
    # - Create a default "Personal" profile for every existing user
    # - Point each user's habits at their Personal profile
    op.execute(
        """
        INSERT INTO profile (
            user_id, name, color_start, color_end, habits_enabled,
            calendar_enabled, publish_to_azure, default_landing, created_date
        )
        SELECT id, 'Personal', '#e0763f', '#c14e6a', TRUE, TRUE, FALSE, 'today', NOW()
        FROM "user"
    """
    )
    op.execute(
        """
        UPDATE habit
        SET profile_id = profile.id
        FROM profile
        WHERE profile.user_id = habit.user_id
          AND profile.name = 'Personal'
    """
    )

    # Every habit now has a profile, so lock the column down
    op.alter_column("habit", "profile_id", nullable=False)
    op.create_foreign_key(
        "fk_habit_profile_id",
        "habit",
        "profile",
        ["profile_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_habit_profile_id"), "habit", ["profile_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the habit columns first (profile_id references profile)
    op.drop_index(op.f("ix_habit_profile_id"), table_name="habit")
    op.drop_constraint("fk_habit_profile_id", "habit", type_="foreignkey")
    op.drop_column("habit", "category")
    op.drop_column("habit", "profile_id")

    # Drop tables in dependency order: task -> project -> profile
    op.drop_index(op.f("ix_task_project_id"), table_name="task")
    op.drop_index(op.f("ix_task_profile_id"), table_name="task")
    op.drop_index(op.f("ix_task_id"), table_name="task")
    op.drop_table("task")
    op.drop_index(op.f("ix_project_profile_id"), table_name="project")
    op.drop_index(op.f("ix_project_id"), table_name="project")
    op.drop_table("project")
    op.drop_index(op.f("ix_profile_user_id"), table_name="profile")
    op.drop_index(op.f("ix_profile_id"), table_name="profile")
    op.drop_table("profile")
