"""drop habit user_id

Revision ID: d0564a171db4
Revises: d5f2a9c7b1e4
Create Date: 2026-07-30 15:17:18.633599

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d0564a171db4"
down_revision: Union[str, Sequence[str], None] = "d5f2a9c7b1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # habit.user_id was redundant with habit.profile_id -> profile.user_id.
    op.drop_constraint("habit_user_id_fkey", "habit", type_="foreignkey")
    op.drop_column("habit", "user_id")


def downgrade() -> None:
    # Re-add non-lossily: backfill each habit's owner from its profile before
    # restoring the NOT NULL and the FK.
    op.add_column("habit", sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE habit
        SET user_id = profile.user_id
        FROM profile
        WHERE habit.profile_id = profile.id
        """
    )
    op.alter_column("habit", "user_id", nullable=False)
    op.create_foreign_key(
        "habit_user_id_fkey",
        "habit",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
