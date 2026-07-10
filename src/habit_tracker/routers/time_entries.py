from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TimeEntryKind
from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models import (
    ProjectTimeSummary,
    TaskTimeSummary,
    TimeEntry,
    TimeEntryCreate,
    TimeEntryList,
    TimeEntryRead,
    TimeEntrySummary,
    TimeEntryUpdate,
)
from habit_tracker.schemas.db_models import Project, Task, User

router = APIRouter(
    prefix="/time-entries",
    tags=["time-entries"],
    responses={404: {"description": "Not found"}},
)


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to naive server-local time.

    Every timestamp in this app is stored naive (like ``datetime.now()``), so
    a client that sends a timezone-aware value is converted to the server's
    local zone and stripped - keeps ended_at/started_at arithmetic from
    raising on aware-vs-naive subtraction.
    """
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _to_read(entry: TimeEntry) -> TimeEntryRead:
    """Build a TimeEntryRead, computing is_running from ended_at."""
    read = TimeEntryRead.model_validate(entry)
    read.is_running = entry.ended_at is None
    return read


async def _validate_task(db: AsyncSession, task_id: int, profile_id: int) -> None:
    """A time entry's task must exist and belong to the same profile (400)."""
    task = await db.get(Task, task_id)
    if not task or task.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task not found or does not belong to this profile",
        )


async def _validate_project(db: AsyncSession, project_id: int, profile_id: int) -> None:
    """A time entry's project must exist and belong to the same profile (400)."""
    project = await db.get(Project, project_id)
    if not project or project.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project not found or does not belong to this profile",
        )


async def _resolve_task_project(
    db: AsyncSession,
    profile_id: int,
    task_id: Optional[int],
    project_id: Optional[int],
) -> tuple[Optional[int], Optional[int]]:
    """Validate and enforce task/project mutual exclusivity for a time entry.

    A task-attached entry derives its project from the task, so a direct
    project_id is dropped when a task is present. Returns the (task_id,
    project_id) pair to persist.
    """
    if task_id is not None:
        await _validate_task(db, task_id, profile_id)
        return task_id, None
    if project_id is not None:
        await _validate_project(db, project_id, profile_id)
        return None, project_id
    return None, None


async def _running_entry(
    db: AsyncSession, profile_id: int, exclude_id: Optional[int] = None
) -> Optional[TimeEntry]:
    """Return the profile's currently-running entry (ended_at IS NULL), if any.

    At most one timer may run per profile so the Today active-timer indicator
    is unambiguous; ``exclude_id`` skips a given entry when re-checking during
    an update.
    """
    query = select(TimeEntry).filter(
        TimeEntry.profile_id == profile_id,
        TimeEntry.ended_at.is_(None),
    )
    if exclude_id is not None:
        query = query.filter(TimeEntry.id != exclude_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none()


async def _get_entry_and_authorize(
    db: AsyncSession, entry_id: int, current_user: User
) -> TimeEntry:
    """Fetch a time entry by ID (404 if missing) and authorize the caller
    against the owning profile."""
    entry = await db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found"
        )
    await authorize_parent_profile(
        db, entry.profile_id, current_user, "time entry"
    )
    return entry


@router.get("/", summary="List time entries for a profile")
async def list_time_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose time entries to list"),
    task_id: Optional[int] = Query(
        default=None, description="Only entries for this task"
    ),
    project_id: Optional[int] = Query(
        default=None,
        description=(
            "Only entries for this project: task-attached entries whose task "
            "belongs to the project, plus adhoc entries attached to it directly"
        ),
    ),
    kind: Optional[int] = Query(
        default=None, description="Only entries of this kind (0 stopwatch, 1 pomodoro)"
    ),
    running: Optional[bool] = Query(
        default=None,
        description="Filter to running (true) or completed (false) entries",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of entries to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of entries to skip"),
) -> TimeEntryList:
    """
    Get a paginated list of time entries belonging to a profile, ordered by
    start time (most recent first).

    - **profile_id**: The profile whose time entries to list (required)
    - **task_id**: Optional. Only entries attached to this task
    - **project_id**: Optional. Entries for this project — task-attached entries
      whose task is in the project plus adhoc entries attached to it directly
    - **kind**: Optional. 0 = stopwatch, 1 = pomodoro
    - **running**: Optional. true = only running entries, false = only completed
    - **limit**: Maximum number of entries to return (default: 100, max: 100)
    - **offset**: Number of entries to skip (default: 0)
    """
    if kind is not None and kind not in [k.value for k in TimeEntryKind]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kind must be a valid TimeEntryKind value",
        )

    await get_owned_profile(db, profile_id, current_user, "time entry")

    filters = [TimeEntry.profile_id == profile_id]
    if task_id is not None:
        filters.append(TimeEntry.task_id == task_id)
    if kind is not None:
        filters.append(TimeEntry.kind == kind)
    if running is not None:
        if running:
            filters.append(TimeEntry.ended_at.is_(None))
        else:
            filters.append(TimeEntry.ended_at.is_not(None))
    if project_id is not None:
        # An entry counts toward a project via its task's project (task-attached)
        # or its own project_id (adhoc); left-join the task for the former.
        filters.append(
            func.coalesce(Task.project_id, TimeEntry.project_id) == project_id
        )

    def scoped(stmt):
        # Only join the task table when resolving a project filter.
        return stmt.outerjoin(Task, TimeEntry.task_id == Task.id) if project_id is not None else stmt

    count_result = await db.execute(
        scoped(select(func.count(TimeEntry.id)).select_from(TimeEntry)).filter(*filters)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        scoped(select(TimeEntry))
        .filter(*filters)
        .order_by(TimeEntry.started_at.desc(), TimeEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()

    return TimeEntryList(
        time_entries=[_to_read(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/", status_code=status.HTTP_201_CREATED, summary="Create a time entry"
)
async def create_time_entry(
    entry: TimeEntryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TimeEntryRead:
    """
    Create a time entry. Two shapes:

    - **Start a timer**: omit both timestamps (or provide only started_at) and
      leave ended_at null. The entry runs until stopped. Only one timer may run
      per profile at a time - starting another returns 409.
    - **Log a completed entry**: provide ended_at (and optionally started_at,
      default now). duration_seconds is computed from the two, never taken from
      the client.

    - **profile_id**: The profile this entry belongs to (required)
    - **task_id**: Optional task to attach the entry to (same profile). Omit for
      untethered / adhoc timing
    - **project_id**: Optional project for adhoc work not tied to a task (same
      profile). Ignored when task_id is set - a task-attached entry's project is
      derived from its task
    - **kind**: 0 = stopwatch (default), 1 = pomodoro
    - **label**: Optional free-text label ("Standup", "Code review", …)
    - **note**: Optional free-text note
    - **started_at**: Optional start time (default: now)
    - **ended_at**: Optional end time. Present = completed log; absent = running
    """
    await get_owned_profile(db, entry.profile_id, current_user, "time entry")

    task_id, project_id = await _resolve_task_project(
        db, entry.profile_id, entry.task_id, entry.project_id
    )

    started = _naive(entry.started_at) or datetime.now()
    ended = _naive(entry.ended_at)

    if ended is not None:
        if ended < started:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ended_at cannot be before started_at",
            )
        duration = int((ended - started).total_seconds())
    else:
        # Starting a running timer - enforce one per profile
        if await _running_entry(db, entry.profile_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A timer is already running for this profile",
            )
        duration = None

    db_entry = TimeEntry(
        profile_id=entry.profile_id,
        task_id=task_id,
        project_id=project_id,
        kind=entry.kind,
        label=entry.label,
        note=entry.note,
        started_at=started,
        ended_at=ended,
        duration_seconds=duration,
    )
    db.add(db_entry)
    await db.commit()
    await db.refresh(db_entry)
    return _to_read(db_entry)


# NOTE: static routes declared BEFORE the dynamic /{entry_id} routes so
# FastAPI does not parse "active"/"summary" as an entry id
@router.get("/active", summary="Get the running time entry for a profile")
async def read_active_time_entry(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose running timer to fetch"),
) -> Optional[TimeEntryRead]:
    """
    Return the profile's currently-running time entry (the one with no
    ended_at), or null when nothing is running. Powers the Today view's
    active-timer indicator.

    - **profile_id**: The profile whose running timer to fetch (required)
    """
    await get_owned_profile(db, profile_id, current_user, "time entry")
    entry = await _running_entry(db, profile_id)
    return _to_read(entry) if entry else None


@router.get("/summary", summary="Aggregate tracked time per task for a profile")
async def time_entry_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose time to aggregate"),
) -> TimeEntrySummary:
    """
    Sum completed tracked time for a profile, bucketed by task and by project.
    Running entries (no ended_at yet) are excluded - only stopped entries
    contribute.

    - **profile_id**: The profile whose time to aggregate (required)

    Returns **per_task** (null task_id = the task-less/adhoc bucket),
    **per_project** (each entry's project resolves to its task's project when
    task-attached, else its direct project_id; null = neither), and the grand
    **total_seconds**.
    """
    await get_owned_profile(db, profile_id, current_user, "time entry")

    completed = (
        TimeEntry.profile_id == profile_id,
        TimeEntry.duration_seconds.is_not(None),
    )

    task_rows = (
        await db.execute(
            select(
                TimeEntry.task_id,
                func.coalesce(func.sum(TimeEntry.duration_seconds), 0),
                func.count(TimeEntry.id),
            )
            .filter(*completed)
            .group_by(TimeEntry.task_id)
        )
    ).all()

    per_task = [
        TaskTimeSummary(
            task_id=row[0], total_seconds=int(row[1]), entry_count=row[2]
        )
        for row in task_rows
    ]
    total = sum(item.total_seconds for item in per_task)

    # A task-attached entry counts toward its task's project; an adhoc entry
    # counts toward its own project_id.
    resolved_project = func.coalesce(Task.project_id, TimeEntry.project_id)
    project_rows = (
        await db.execute(
            select(
                resolved_project,
                func.coalesce(func.sum(TimeEntry.duration_seconds), 0),
                func.count(TimeEntry.id),
            )
            .select_from(TimeEntry)
            .outerjoin(Task, TimeEntry.task_id == Task.id)
            .filter(*completed)
            .group_by(resolved_project)
        )
    ).all()

    per_project = [
        ProjectTimeSummary(
            project_id=row[0], total_seconds=int(row[1]), entry_count=row[2]
        )
        for row in project_rows
    ]

    return TimeEntrySummary(
        profile_id=profile_id,
        per_task=per_task,
        per_project=per_project,
        total_seconds=total,
    )


@router.post("/{entry_id}/stop", summary="Stop a running time entry")
async def stop_time_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TimeEntryRead:
    """
    Stop a running time entry: stamps ended_at with the server clock and
    computes duration_seconds. Returns 400 if the entry is already stopped.

    - **entry_id**: The unique identifier of the entry to stop
    """
    entry = await _get_entry_and_authorize(db, entry_id, current_user)
    if entry.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Time entry is already stopped",
        )
    now = datetime.now()
    entry.ended_at = now
    # Clamp against clock skew so a stop can never record negative time
    entry.duration_seconds = max(0, int((now - entry.started_at).total_seconds()))
    entry.updated_date = now
    await db.commit()
    await db.refresh(entry)
    return _to_read(entry)


@router.get("/{entry_id}", summary="Get a time entry by ID")
async def read_time_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TimeEntryRead:
    """
    Retrieve a specific time entry by its ID.

    - **entry_id**: The unique identifier of the entry to retrieve
    """
    entry = await _get_entry_and_authorize(db, entry_id, current_user)
    return _to_read(entry)


@router.patch("/{entry_id}", summary="Update a time entry (partial update)")
async def patch_time_entry(
    entry_id: int,
    entry_update: TimeEntryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TimeEntryRead:
    """
    Update specific fields of a time entry. Only provided fields are updated.

    - **entry_id**: The unique identifier of the entry to update

    You can update any combination of these fields:
    - **task_id**: Attach to a task in the same profile, or null to detach.
      Setting a task clears any direct project (project derived from the task)
    - **project_id**: Attach adhoc to a project (same profile), or null to
      detach. Ignored when a task is attached
    - **kind**: 0 = stopwatch, 1 = pomodoro
    - **label**: Free-text label (null to clear)
    - **note**: Free-text note (null to clear)
    - **started_at**: Start time
    - **ended_at**: End time; null reopens the entry as a running timer

    duration_seconds is always recomputed from the resulting timestamps
    (null while running). If the update would leave a second running timer in
    the profile, it returns 409; if ended_at ends up before started_at, 400.
    """
    entry = await _get_entry_and_authorize(db, entry_id, current_user)

    data = entry_update.model_dump(exclude_unset=True)

    # Resolve task/project mutual exclusivity when either is being changed.
    # Explicit non-null wins (task takes precedence over project); if only one
    # is cleared, re-resolve against the entry's existing counterpart.
    if "task_id" in data or "project_id" in data:
        if data.get("task_id") is not None:
            resolved_task, resolved_project = await _resolve_task_project(
                db, entry.profile_id, data["task_id"], None
            )
        elif data.get("project_id") is not None:
            resolved_task, resolved_project = await _resolve_task_project(
                db, entry.profile_id, None, data["project_id"]
            )
        else:
            target_task = data["task_id"] if "task_id" in data else entry.task_id
            target_project = (
                data["project_id"] if "project_id" in data else entry.project_id
            )
            resolved_task, resolved_project = await _resolve_task_project(
                db, entry.profile_id, target_task, target_project
            )
        data["task_id"] = resolved_task
        data["project_id"] = resolved_project

    if "started_at" in data:
        data["started_at"] = _naive(data["started_at"])
    if "ended_at" in data:
        data["ended_at"] = _naive(data["ended_at"])

    for key, value in data.items():
        setattr(entry, key, value)

    if entry.ended_at is not None:
        if entry.ended_at < entry.started_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ended_at cannot be before started_at",
            )
        entry.duration_seconds = int(
            (entry.ended_at - entry.started_at).total_seconds()
        )
    else:
        # Reopened / still running - keep the one-timer-per-profile invariant
        if await _running_entry(db, entry.profile_id, exclude_id=entry.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A timer is already running for this profile",
            )
        entry.duration_seconds = None

    entry.updated_date = datetime.now()  # server-stamped, never client-set
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Time entry change violates a database constraint",
        )
    await db.refresh(entry)
    return _to_read(entry)


@router.delete("/{entry_id}", summary="Delete a time entry")
async def delete_time_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a time entry by its ID. This cannot be undone.

    - **entry_id**: The unique identifier of the entry to delete
    """
    entry = await _get_entry_and_authorize(db, entry_id, current_user)
    await db.delete(entry)
    await db.commit()
    return JSONResponse(content={"detail": "Time entry deleted successfully"})
