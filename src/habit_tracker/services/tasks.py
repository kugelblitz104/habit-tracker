"""The rules for writing a task, shared by create and update.

A task's status decides its `closed_date` and whether it may carry scheduled
fields; its slug follows its title and profile; its project and parent must
sit in its profile, and subtasks nest one level deep. The routers keep auth,
the commit and the read model. Backup restore deliberately bypasses this
module, because it preserves stored values verbatim.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import CLOSED_STATUSES, TaskStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.schemas.db_models import Profile, Project, Task
from habit_tracker.services.notifications import TASK, reschedule
from habit_tracker.services.profile_moves import (
    move_task_dependents,
    refresh_slug,
    target_profile,
)


async def add_task(db: AsyncSession, data: dict) -> Task:
    """Validate `data` (a TaskCreate dump), add the new task to the session and
    schedule its reminders. Does not commit.

    The caller has already authorised `data["profile_id"]`. Raises 400 when
    the project or parent is missing or in another profile, or when the
    parent is itself a subtask.
    """
    profile_id = data["profile_id"]
    await _validate_project(
        db,
        data.get("project_id"),
        profile_id,
        "Project not found or does not belong to this profile",
    )
    if data.get("parent_id") is not None:
        await _validate_parent_task(
            db,
            data["parent_id"],
            profile_id,
            "Parent task not found or does not belong to this profile",
        )

    db_task = Task()
    # Added only once it has a slug: in an autoflushing session the slug query
    # would otherwise flush it with a NULL slug.
    await _apply_fields(db, db_task, data)
    db.add(db_task)
    await reschedule(db, TASK, db_task)
    return db_task


async def apply_task_update(
    db: AsyncSession, db_task: Task, profile: Profile, data: dict
) -> None:
    """Apply `data` (a TaskUpdate dump with exclude_unset) to `db_task`, move
    its time entries and linked countdowns on a profile move, stamp
    `updated_date` and reschedule its reminders. Does not commit.

    `profile` is the task's current owning profile. Validations fire in this
    order, all 400 except the last: the target profile (see
    `profile_moves.target_profile`), the resulting project, a move of a task
    that has subtasks, the resulting parent (self, missing or foreign, itself
    a subtask), a task with subtasks becoming a subtask, then 422 for a
    `closed_date` on a task that ends up active.
    """
    task_id = db_task.id

    # Memoised subtask count: the profile-move check and the parent_id-set
    # check below are each only conditionally reached, and the first raises
    # before the second when both apply, so at most one query ever runs -
    # this just avoids writing the same query twice.
    cached_subtask_total: int | None = None

    async def subtask_total() -> int:
        nonlocal cached_subtask_total
        if cached_subtask_total is None:
            cached_subtask_total = (
                await db.scalar(
                    select(func.count(Task.id)).filter(Task.parent_id == task_id)
                )
                or 0
            )
        return cached_subtask_total

    # Validate a profile move: new profile must belong to the same user, and
    # the task's project (if any) must belong to the new profile
    target = await target_profile(db, profile, data.get("profile_id"))
    target_profile_id = target.id if target is not None else db_task.profile_id

    # Validate the resulting project (moved or kept) against the resulting profile
    await _validate_project(
        db,
        data.get("project_id", db_task.project_id),
        target_profile_id,
        "Project not found or does not belong to the task's profile",
    )

    # A profile move may not leave subtasks behind: a task that has subtasks
    # cannot move (mirrors the project rule - profile coherence is enforced,
    # never silently fixed)
    if target is not None and await subtask_total():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot move a task with subtasks to another profile",
        )

    # Validate the resulting parent (moved or kept) against the resulting
    # profile - so moving a subtask to another profile fails unless parent_id
    # is nulled in the same request
    target_parent_id = data.get("parent_id", db_task.parent_id)
    if target_parent_id is not None:
        if target_parent_id == task_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A task cannot be its own parent",
            )
        await _validate_parent_task(
            db,
            target_parent_id,
            target_profile_id,
            "Parent task not found or does not belong to the task's profile",
        )
        # ONE level deep: a task that has subtasks cannot itself become a
        # subtask (only reachable when parent_id is being set - an existing
        # subtask can never have subtasks of its own)
        if "parent_id" in data and await subtask_total():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A task with subtasks cannot itself become a subtask",
            )

    await _apply_fields(db, db_task, data)
    if target is not None:
        await move_task_dependents(db, [task_id], target.id)

    db_task.updated_date = utc_now()  # server-stamped, never client-set
    await reschedule(db, TASK, db_task)


async def _apply_fields(db: AsyncSession, db_task: Task, data: dict) -> None:
    """Write `data` onto `db_task` with the status, scheduling and slug rules.

    Serves a new, empty `Task` as well as a stored one: a new task has no
    status (so it was never closed), no title and no profile, so it always
    gets a slug. Raises 422 when `data` carries a `closed_date` and the
    resulting status is active. Pops `closed_date` from `data`.
    """
    # Status transitions: entering done/cancelled stamps closed_date unless
    # the same patch supplied one, which is what makes "close it today, dated
    # last Tuesday" a single request. Leaving them for an active status
    # clears it.
    supplied_closed_date = "closed_date" in data
    was_closed = db_task.status in CLOSED_STATUSES
    is_closing = data["status"] in CLOSED_STATUSES if "status" in data else was_closed

    if supplied_closed_date and not is_closing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="closed_date can only be set on a done or cancelled task",
        )

    if "status" in data:
        if is_closing:
            if supplied_closed_date:
                db_task.closed_date = data["closed_date"]
            elif not was_closed:
                db_task.closed_date = utc_now()
        else:
            db_task.closed_date = None
    elif supplied_closed_date:
        db_task.closed_date = data["closed_date"]

    # Applied above; must not also go through the generic setattr loop below.
    data.pop("closed_date", None)

    previous_title = db_task.title
    previous_profile_id = db_task.profile_id

    for key, value in data.items():
        setattr(db_task, key, value)

    await refresh_slug(
        db,
        db_task,
        source=db_task.title,
        previous_source=previous_title,
        previous_profile_id=previous_profile_id,
    )

    # Scheduled data only lives on SCHEDULED tasks; any other resulting status
    # forces the scheduled fields null (prevents orphaned scheduled data). This
    # fires both when status changes away from SCHEDULED and when the task was
    # never scheduled, regardless of whether the scheduled fields were sent
    if db_task.status != TaskStatus.SCHEDULED:
        db_task.scheduled_date = None
        db_task.scheduled_time = None


async def _validate_project(
    db: AsyncSession, project_id: int | None, profile_id: int, not_found_detail: str
) -> None:
    """Raise 400 with `not_found_detail` unless `project_id` is None or names a
    project in `profile_id`."""
    if project_id is None:
        return
    project = await db.get(Project, project_id)
    if not project or project.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=not_found_detail,
        )


async def _validate_parent_task(
    db: AsyncSession, parent_id: int, profile_id: int, not_found_detail: str
) -> None:
    """Validate a task's prospective parent (400 on any violation).

    The parent must exist, belong to ``profile_id``, and not itself be a
    subtask (subtasks nest exactly ONE level deep).
    """
    parent = await db.get(Task, parent_id)
    if not parent or parent.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=not_found_detail,
        )
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subtasks can only be nested one level deep",
        )
