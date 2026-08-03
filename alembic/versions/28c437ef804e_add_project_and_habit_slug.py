"""add project and habit slug

Revision ID: 28c437ef804e
Revises: 5eb9aeab1c1e
Create Date: 2026-08-03 14:37:18.940232

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from habit_tracker.core.slugs import next_free_slug, slugify


# revision identifiers, used by Alembic.
revision: str = "28c437ef804e"
down_revision: Union[str, Sequence[str], None] = "5eb9aeab1c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, the column its slug derives from). Both are NOT NULL, so the backfill
# below always has something to slugify. Same shape as 5eb9aeab1c1e, which did
# this for `task.title`.
_SLUGGED = (("project", "name"), ("habit", "name"))


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()

    for table, source in _SLUGGED:
        # Added nullable, backfilled, then tightened to NOT NULL - the column's
        # real shape. Autogenerate emitted a bare NOT NULL add, which fails on
        # any table with existing rows. A server_default instead would have to be
        # dropped again, and would give a row the backfill missed a
        # wrong-but-valid slug rather than failing loudly here.
        op.add_column(table, sa.Column("slug", sa.String(), nullable=True))
        op.create_index(op.f(f"ix_{table}_slug"), table, ["slug"], unique=False)

        # Ordered by id within each profile so the oldest row wins the clean slug
        # and later duplicates number off it, matching runtime allocation.
        # `table`/`source` come from the tuple above, never from user input.
        rows = connection.execute(
            sa.text(
                f"SELECT id, profile_id, {source} FROM {table} ORDER BY profile_id, id"
            )
        ).fetchall()

        taken_by_profile: dict[int, set[str]] = {}
        for row_id, profile_id, source_value in rows:
            taken = taken_by_profile.setdefault(profile_id, set())
            slug = next_free_slug(slugify(source_value), taken)
            taken.add(slug)
            connection.execute(
                sa.text(f"UPDATE {table} SET slug = :slug WHERE id = :id"),
                {"slug": slug, "id": row_id},
            )

        op.alter_column(table, "slug", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table, _ in _SLUGGED:
        op.drop_index(op.f(f"ix_{table}_slug"), table_name=table)
        op.drop_column(table, "slug")
