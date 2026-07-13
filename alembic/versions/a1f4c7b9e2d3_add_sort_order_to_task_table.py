"""add_sort_order_to_task_table

Revision ID: a1f4c7b9e2d3
Revises: 7e7f1df4ed0f
Create Date: 2026-07-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1f4c7b9e2d3"
down_revision: Union[str, Sequence[str], None] = "7e7f1df4ed0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "task",
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_index(op.f("ix_task_sort_order"), "task", ["sort_order"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_task_sort_order"), table_name="task")
    op.drop_column("task", "sort_order")
