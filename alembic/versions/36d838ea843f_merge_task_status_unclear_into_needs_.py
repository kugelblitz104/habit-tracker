"""merge task status unclear into needs info

Revision ID: 36d838ea843f
Revises: 5508c9153583
Create Date: 2026-08-13 09:52:46.629646

Data only - no column moves, so there is nothing for autogenerate to find.
One UPDATE covers subtasks too; they are rows in the same table.

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "36d838ea843f"
down_revision: Union[str, Sequence[str], None] = "5508c9153583"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UNCLEAR = 9
_NEEDS_INFO = 4


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"UPDATE task SET status = {_NEEDS_INFO} WHERE status = {_UNCLEAR}")


def downgrade() -> None:
    """Downgrade schema.

    Irreversible: a task migrated off Unclear is indistinguishable from one
    that was already Needs info, so there is nothing to restore.
    """
