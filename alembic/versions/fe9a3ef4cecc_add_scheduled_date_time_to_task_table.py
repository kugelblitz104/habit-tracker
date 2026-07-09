"""add_scheduled_date_time_to_task_table

Revision ID: fe9a3ef4cecc
Revises: 9ed98b38cd9f
Create Date: 2026-07-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fe9a3ef4cecc"
down_revision: Union[str, Sequence[str], None] = "9ed98b38cd9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("task", sa.Column("scheduled_date", sa.Date(), nullable=True))
    op.add_column("task", sa.Column("scheduled_time", sa.Time(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("task", "scheduled_time")
    op.drop_column("task", "scheduled_date")
