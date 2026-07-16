"""add integration_connection table and task.source

Adds the per-profile integration_connection table (Azure DevOps / GitHub, PAT
stored encrypted) plus a task.source column and a unique constraint making
imported-item sync idempotent.

Revision ID: b2c5e9d1a4f7
Revises: a1f4c7b9e2d3
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c5e9d1a4f7'
down_revision: Union[str, Sequence[str], None] = 'a1f4c7b9e2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "integration_connection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("organization", sa.String(), nullable=True),
        sa.Column("project", sa.String(), nullable=True),
        sa.Column("work_item_type", sa.String(), nullable=True),
        sa.Column("default_repo", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("updated_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_integration_connection_id"),
        "integration_connection",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_connection_profile_id"),
        "integration_connection",
        ["profile_id"],
        unique=False,
    )

    op.add_column("task", sa.Column("source", sa.String(), nullable=True))
    op.create_unique_constraint(
        "uix_task_profile_source_external_ref",
        "task",
        ["profile_id", "source", "external_ref"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uix_task_profile_source_external_ref", "task", type_="unique"
    )
    op.drop_column("task", "source")

    op.drop_index(
        op.f("ix_integration_connection_profile_id"),
        table_name="integration_connection",
    )
    op.drop_index(
        op.f("ix_integration_connection_id"), table_name="integration_connection"
    )
    op.drop_table("integration_connection")
