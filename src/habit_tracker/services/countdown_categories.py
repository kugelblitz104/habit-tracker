"""Resolve a countdown's category record from its free-text name.

`Countdown.category` is the free-text name a client sets; `Countdown.category_id`
points at the `CountdownCategory` row that owns the group's colour. This module
is the only place that name is turned into, or matched against, a record.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.schemas.db_models import CountdownCategory


async def find_or_create(
    db: AsyncSession,
    *,
    profile_id: int,
    name: str,
    seed_color: str | None = None,
) -> CountdownCategory:
    """Return the profile's category named `name`, inserting it if absent.

    `name` is trimmed; matching is case-sensitive, so "bills" and "Bills" are
    two separate categories.

    `seed_color` is applied only when inserting a new row. An existing
    category's `color` is left untouched.

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

    row = CountdownCategory(profile_id=profile_id, name=clean, color=seed_color)
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
    seed_color: str | None = None,
) -> tuple[int | None, str | None]:
    """Map a countdown's requested category name to `(category_id, name)`.

    A `None` or blank name returns `(None, None)`: the countdown is
    uncategorised and no record is created.
    """
    if name is None or not name.strip():
        return None, None
    row = await find_or_create(
        db, profile_id=profile_id, name=name, seed_color=seed_color
    )
    return row.id, row.name
