"""add time_entry label + project_id, profile show_estimated_effort

Revision ID: 7e7f1df4ed0f
Revises: 44bfe95b7b50
Create Date: 2026-07-10 13:31:43.505383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e7f1df4ed0f'
down_revision: Union[str, Sequence[str], None] = '44bfe95b7b50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Profile: estimated-effort field visibility toggle
    op.add_column(
        "profile",
        sa.Column(
            "show_estimated_effort",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Time entry: free-text label + direct (adhoc) project attachment
    op.add_column("time_entry", sa.Column("label", sa.String(), nullable=True))
    op.add_column("time_entry", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_time_entry_project_id"), "time_entry", ["project_id"], unique=False
    )
    op.create_foreign_key(
        "fk_time_entry_project_id",
        "time_entry",
        "project",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_time_entry_project_id", "time_entry", type_="foreignkey")
    op.drop_index(op.f("ix_time_entry_project_id"), table_name="time_entry")
    op.drop_column("time_entry", "project_id")
    op.drop_column("time_entry", "label")

    op.drop_column("profile", "show_estimated_effort")
