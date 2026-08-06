"""Resolve a countdown's category record from a name or an id.

`Countdown.category_id` points at the `CountdownCategory` row that owns the
group's colour. This module is the only place a name is turned into, or
matched against, a record.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.schemas.db_models import CountdownCategory


async def find_or_create(
    db: AsyncSession,
    *,
    profile_id: int,
    name: str,
) -> CountdownCategory:
    """Return the profile's category named `name`, inserting it if absent.

    `name` is trimmed; matching is case-sensitive, so "bills" and "Bills" are
    two separate categories. A new category is created with no colour.

    Reads then inserts rather than upserting: the unique constraint on
    `(profile_id, name)` is the real guard, and a concurrent duplicate insert
    surfaces as an `IntegrityError` for the caller to handle.
    """
    clean = name.strip()
    existing = (
        await db.execute(
            select(CountdownCategory).where(
                CountdownCategory.profile_id == profile_id,
                CountdownCategory.name == clean,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = CountdownCategory(profile_id=profile_id, name=clean)
    db.add(row)
    await db.flush()
    return row


async def get_in_profile(
    db: AsyncSession, *, profile_id: int, category_id: int
) -> CountdownCategory | None:
    """Return the category with this id in this profile, or None.

    Scoped rather than a plain `db.get`, so a client cannot select a category
    belonging to another profile by guessing its id.
    """
    return (
        await db.execute(
            select(CountdownCategory).where(
                CountdownCategory.id == category_id,
                CountdownCategory.profile_id == profile_id,
            )
        )
    ).scalar_one_or_none()


async def resolve_for_countdown(
    db: AsyncSession,
    *,
    profile_id: int,
    name: str | None,
) -> int | None:
    """Map a category name to its record id, creating the record if new.

    A `None` or blank name returns `None`: the countdown is uncategorised and no
    record is created. Called only by the backup importer, which is the one path
    that still files a countdown into a group by name.
    """
    if name is None or not name.strip():
        return None
    row = await find_or_create(db, profile_id=profile_id, name=name)
    return row.id
