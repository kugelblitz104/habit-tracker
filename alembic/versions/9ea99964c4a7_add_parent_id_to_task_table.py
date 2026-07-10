"""add_parent_id_to_task_table

Revision ID: 9ea99964c4a7
Revises: c8bde5259f5a
Create Date: 2026-07-09 22:43:43.589537

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ea99964c4a7'
down_revision: Union[str, Sequence[str], None] = 'c8bde5259f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("task", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_task_parent_id",
        "task",
        "task",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_task_parent_id"), "task", ["parent_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_task_parent_id"), table_name="task")
    op.drop_constraint("fk_task_parent_id", "task", type_="foreignkey")
    op.drop_column("task", "parent_id")
