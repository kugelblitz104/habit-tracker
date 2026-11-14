"""Moving rows to another profile of the same user.

The rule is profile coherence: everything that hangs off a moved row moves
with it, so nothing is left in one profile pointing at a parent in another.
A task takes its time entries and the countdowns linked to it; a project takes
its tasks, their subtasks, everything those take, and the time entries on the
project itself. Slugs are unique per profile, so every moved row with a slug
is re-slugged in the target.
"""

from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.slugs import allocate_slug
from habit_tracker.schemas.db_models import (
    Countdown,
    Habit,
    Profile,
    Project,
    Task,
    TimeEntry,
)
from habit_tracker.services.countdown_categories import carry_to_profile
from habit_tracker.services.notifications import COUNTDOWN, reschedule


async def target_profile(
    db: AsyncSession, current: Profile, new_profile_id: int | None
) -> Profile | None:
    """The profile an update moves a row to, or None when it is not a move.

    `current` is the row's owning profile and `new_profile_id` the update's
    `profile_id`; None or the current id means the row stays. Raises 400 when
    the target is missing or belongs to a different user than `current`.
    """
    if new_profile_id is None or new_profile_id == current.id:
        return None
    target = await db.get(Profile, new_profile_id)
    if target is None or target.user_id != current.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New profile not found or does not belong to the same user",
        )
    return target


async def refresh_slug(
    db: AsyncSession,
    row: Task | Project | Habit,
    *,
    source: str,
    previous_source: str | None,
    previous_profile_id: int | None,
) -> None:
    """Re-derive `row.slug` if its source text or its profile changed.

    Call after the update's fields are applied. `source` is the row's title or
    name. A move re-slugs even when the text is unchanged, because the clean
    slug may already be taken in the target profile. A new row (previous
    values None) always gets one.
    """
    if source != previous_source or row.profile_id != previous_profile_id:
        row.slug = await allocate_slug(
            db,
            type(row),
            profile_id=row.profile_id,
            source=source,
            exclude_id=row.id,
        )


async def move_task_dependents(
    db: AsyncSession, task_ids: Sequence[int], profile_id: int
) -> None:
    """Move what hangs off `task_ids` into `profile_id`: their time entries and
    the countdowns linked to them.

    A moved countdown is refiled under the target profile's category of the
    same name, since a category belongs to one profile, and its schedule row is
    rewritten for the new profile.
    """
    await db.execute(
        update(TimeEntry)
        .where(TimeEntry.task_id.in_(task_ids))
        .values(profile_id=profile_id)
    )
    countdowns = await db.scalars(
        select(Countdown).where(Countdown.task_id.in_(task_ids))
    )
    for countdown in countdowns.all():
        countdown.category_id = await carry_to_profile(
            db, category_id=countdown.category_id, profile_id=profile_id
        )
        countdown.profile_id = profile_id
        await reschedule(db, COUNTDOWN, countdown)


async def move_project_contents(
    db: AsyncSession, project_id: int, profile_id: int
) -> None:
    """Move a project's tasks, their subtasks and everything hanging off them
    (see `move_task_dependents`), plus the time entries attached to the project
    itself, into `profile_id`.

    Subtasks need their own clause: a subtask usually has no `project_id` and
    reaches its project through its parent, so selecting on `project_id` alone
    leaves it behind with a parent in another profile.

    Each task is flushed before the next slug allocation, because
    `allocate_slug` reads the database and the session does not autoflush:
    without it, two moved tasks sharing a title would get the same slug.
    """
    in_project = select(Task.id).where(Task.project_id == project_id)
    tasks = (
        await db.scalars(
            select(Task)
            .where(or_(Task.project_id == project_id, Task.parent_id.in_(in_project)))
            .order_by(Task.id)
        )
    ).all()
    for task in tasks:
        task.profile_id = profile_id
        task.slug = await allocate_slug(
            db, Task, profile_id=profile_id, source=task.title, exclude_id=task.id
        )
        await db.flush()
    await move_task_dependents(db, [task.id for task in tasks], profile_id)
    await db.execute(
        update(TimeEntry)
        .where(TimeEntry.project_id == project_id)
        .values(profile_id=profile_id)
    )
