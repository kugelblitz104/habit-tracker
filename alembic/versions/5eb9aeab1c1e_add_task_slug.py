"""add task slug

Revision ID: 5eb9aeab1c1e
Revises: d0564a171db4
Create Date: 2026-08-03 10:21:13.963674

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from habit_tracker.core.slugs import next_free_slug, slugify


# revision identifiers, used by Alembic.
revision: str = "5eb9aeab1c1e"
down_revision: Union[str, Sequence[str], None] = "d0564a171db4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added nullable, backfilled, then tightened to NOT NULL - the column's real
    # shape. Doing it in one step would need a server_default, which would then
    # have to be dropped again, and would silently give any row the migration
    # missed a wrong-but-valid slug instead of failing loudly here.
    op.add_column("task", sa.Column("slug", sa.String(), nullable=True))
    op.create_index(op.f("ix_task_slug"), "task", ["slug"], unique=False)

    # Backfill: every existing task gets the slug it would have been created
    # with. Ordered by id within each profile so the oldest task wins the clean
    # slug and later duplicates number off it, matching how allocation works at
    # runtime.
    #
    # `slugify` / `next_free_slug` are imported from the application rather than
    # copied in, so there is exactly one definition of the rule. Both are pure
    # and have no other callers' state to depend on; the tradeoff is that this
    # migration is not frozen against future edits to them, which is acceptable
    # because it only ever produces slugs, never reads them back.
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, profile_id, title FROM task ORDER BY profile_id, id")
    ).fetchall()

    taken_by_profile: dict[int, set[str]] = {}
    for task_id, profile_id, title in rows:
        taken = taken_by_profile.setdefault(profile_id, set())
        slug = next_free_slug(slugify(title), taken)
        taken.add(slug)
        connection.execute(
            sa.text("UPDATE task SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": task_id},
        )

    op.alter_column("task", "slug", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_task_slug"), table_name="task")
    op.drop_column("task", "slug")
