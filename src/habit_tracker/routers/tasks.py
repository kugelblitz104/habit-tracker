from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TaskBand, TaskStatus, compute_band
from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models import (
    Profile,
    Project,
    Task,
    TaskCreate,
    TaskList,
    TaskRead,
    TaskUpdate,
)
from habit_tracker.schemas.db_models import User
from habit_tracker.services.task_export import render_tasks_markdown

router = APIRouter(
    prefix="/tasks", tags=["tasks"], responses={404: {"description": "Not found"}}
)

CLOSED_STATUSES = (TaskStatus.DONE.value, TaskStatus.CANCELLED.value)


def _task_to_read(
    task: Task,
    today: date | None = None,
    subtask_counts: dict[int, tuple[int, int]] | None = None,
) -> TaskRead:
    """Build a TaskRead with its computed urgency band and subtask counts.

    Bands are computed uniformly for every task - subtasks get the natural
    band their own status/priority/dates produce (no special-casing); the
    frontend nests subtasks under their parent and ignores their band.

    ``subtask_counts`` maps parent task id -> (subtask_count, done_count);
    tasks without an entry (including all subtasks) get 0/0.
    """
    task_read = TaskRead.model_validate(task)
    task_read.band = compute_band(
        task.status,
        task.priority,
        task.due_date,
        scheduled_date=task.scheduled_date,
        today=today,
    )
    if subtask_counts is not None:
        count, done_count = subtask_counts.get(task.id, (0, 0))
        task_read.subtask_count = count
        task_read.subtask_done_count = done_count
    return task_read


async def _get_subtask_counts(
    db: AsyncSession,
    *,
    profile_id: int | None = None,
    parent_id: int | None = None,
) -> dict[int, tuple[int, int]]:
    """Aggregate subtask counts, keyed by parent task id.

    One grouped query - no per-task N+1: for the list endpoint pass
    ``profile_id`` (counts for every parent in the profile); for a single
    task pass ``parent_id``. "Done" means status DONE only - cancelled
    subtasks count toward the total but not the done count.
    """
    query = (
        select(
            Task.parent_id,
            func.count(Task.id),
            func.count(Task.id).filter(Task.status == TaskStatus.DONE.value),
        )
        .filter(Task.parent_id.is_not(None))
        .group_by(Task.parent_id)
    )
    if profile_id is not None:
        query = query.filter(Task.profile_id == profile_id)
    if parent_id is not None:
        query = query.filter(Task.parent_id == parent_id)
    result = await db.execute(query)
    return {row[0]: (row[1], row[2]) for row in result.all()}


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


async def _get_task_and_profile(
    db: AsyncSession, task_id: int, current_user: User
) -> tuple[Task, Profile]:
    """Fetch a task by ID (404 if missing) and authorize the caller against
    the owning profile. Returns the task with its (FK-guaranteed) profile."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    profile = await authorize_parent_profile(db, task.profile_id, current_user, "task")
    return task, profile


@router.get("/", summary="List tasks for a profile")
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose tasks to list"),
    project_id: Optional[int] = Query(
        default=None, description="Only tasks in this project"
    ),
    band: Optional[str] = Query(
        default=None,
        description="Only tasks in this computed band (now, soon, whenever, hidden)",
    ),
    task_status: Optional[int] = Query(
        default=None, alias="status", description="Only tasks with this status value"
    ),
    include_closed: bool = Query(
        default=False,
        description="Include done/cancelled tasks (excluded by default)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of tasks to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of tasks to skip"),
) -> TaskList:
    """
    Get a paginated list of tasks belonging to a profile. Each task carries
    its computed urgency **band** (now/soon/whenever/hidden).

    - **profile_id**: The profile whose tasks to list (required)
    - **project_id**: Optional. Only tasks in this project
    - **band**: Optional. Filter by computed band. Bands are date-relative,
      so this filter is applied after fetching the profile's tasks
    - **status**: Optional. Filter by exact task status value
    - **include_closed**: Include done/cancelled tasks (default: false). For
      the "Completed & closed" view pass `include_closed=true&band=hidden` -
      that view is ordered by closed date (most recent first)
    - **limit**: Maximum number of tasks to return (default: 100, max: 100)
    - **offset**: Number of tasks to skip (default: 0)

    Active tasks are ordered by priority (desc), due date (asc, no due date
    last), then creation date (asc).

    Subtasks are returned in the same response as their parents, with
    **parent_id** set, so the frontend can nest them without extra requests.
    A subtask's **band** is the natural value its own status/priority/dates
    would produce (no special-casing) - the frontend ignores it and groups
    the subtask under its parent instead. Every task also carries
    **subtask_count** / **subtask_done_count** (done = status DONE only),
    computed in a single grouped query.
    """
    if band is not None and band not in [b.value for b in TaskBand]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Band must be one of: now, soon, whenever, hidden",
        )
    if task_status is not None and task_status not in [s.value for s in TaskStatus]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be a valid TaskStatus value",
        )

    await get_owned_profile(db, profile_id, current_user, "task")

    query = select(Task).filter(Task.profile_id == profile_id)
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if task_status is not None:
        query = query.filter(Task.status == task_status)
    elif not include_closed:
        query = query.filter(Task.status.not_in(CLOSED_STATUSES))

    if include_closed and band == TaskBand.HIDDEN:
        query = query.order_by(Task.closed_date.desc())
    else:
        query = query.order_by(
            Task.priority.desc(),
            Task.due_date.asc().nulls_last(),
            Task.created_date.asc(),
        )

    result = await db.execute(query)
    db_tasks = result.scalars().all()

    # One aggregate query for the whole profile's subtask counts (no N+1)
    subtask_counts = await _get_subtask_counts(db, profile_id=profile_id)

    # Bands are date-relative and never stored, so band filtering happens in
    # Python after fetching; limit/offset apply to the band-filtered list
    today = date.today()
    tasks_read = [_task_to_read(t, today, subtask_counts) for t in db_tasks]
    if band is not None:
        tasks_read = [t for t in tasks_read if t.band == band]

    total = len(tasks_read)
    tasks_read = tasks_read[offset : offset + limit]

    return TaskList(
        tasks=tasks_read,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new task")
async def create_task(
    task: TaskCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskRead:
    """
    Create a new task. Quick-capture friendly: only **profile_id** and
    **title** are required, everything else is defaulted.

    - **profile_id**: The ID of the profile this task belongs to
    - **title**: Title of the task
    - **notes**: Optional markdown notes about the task
    - **priority**: 0 none / 1 low / 2 medium / 3 high (default: 0)
    - **due_date**: Optional due date
    - **due_time**: Optional due time
    - **scheduled_date**: Optional date the task is scheduled for
    - **scheduled_time**: Optional time the task is scheduled for
    - **status**: Task status value (default: 0 = open)
    - **block_reason**: Optional free-text reason when blocked
    - **external_ref**: Optional external reference (e.g. "ADO-2841")
    - **external_url**: Optional external URL
    - **project_id**: Optional project (must belong to the same profile)
    - **parent_id**: Optional parent task, making this task a subtask. The
      parent must belong to the same profile and must not itself be a
      subtask (subtasks nest exactly one level deep)

    Scheduled data only lives on SCHEDULED tasks: if the created status is
    anything other than SCHEDULED, scheduled_date/scheduled_time are forced to
    null even when supplied (prevents orphaned scheduled data).
    """
    await get_owned_profile(db, task.profile_id, current_user, "task")

    if task.project_id is not None:
        project = await db.get(Project, task.project_id)
        if not project or project.profile_id != task.profile_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project not found or does not belong to this profile",
            )

    if task.parent_id is not None:
        await _validate_parent_task(
            db,
            task.parent_id,
            task.profile_id,
            "Parent task not found or does not belong to this profile",
        )

    db_task = Task(**task.model_dump())
    if db_task.status in CLOSED_STATUSES:
        db_task.closed_date = datetime.now()
    # Scheduled data only lives on SCHEDULED tasks; any other status forces the
    # scheduled fields null (prevents orphaned scheduled data)
    if db_task.status != TaskStatus.SCHEDULED:
        db_task.scheduled_date = None
        db_task.scheduled_time = None
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return _task_to_read(db_task)


# NOTE: must stay declared before GET /{task_id} so "/export" is not
# captured by the task_id path parameter
@router.get(
    "/export",
    response_class=PlainTextResponse,
    summary="Export a profile's tasks as Markdown",
)
async def export_tasks_markdown(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose tasks to export"),
) -> PlainTextResponse:
    """
    Export all of a profile's tasks as a Markdown document (`text/markdown`).
    The response body is the raw document - not JSON-wrapped - so the client
    can save it directly as a `.md` file.

    - **profile_id**: The profile whose tasks to export (required)

    Tasks are grouped by computed urgency band (Now / Soon / Whenever, plus a
    "Completed & cancelled" section for done/cancelled tasks); empty sections
    are omitted. Each task is a checklist line (`- [x]` when done) with
    indented detail bullets for the fields that are set. Subtasks never
    appear as top-level entries - they render as indented checklist lines
    under their parent, wherever the parent lands. Ordering matches the
    tasks list endpoint: active bands by priority (desc), due date (asc, no
    due date last), then creation date; the closed section by closed date
    (most recent first).
    """
    profile = await get_owned_profile(db, profile_id, current_user, "task")

    result = await db.execute(select(Task).filter(Task.profile_id == profile_id))
    tasks = result.scalars().all()

    project_result = await db.execute(
        select(Project).filter(Project.profile_id == profile_id)
    )
    project_names = {p.id: p.name for p in project_result.scalars().all()}

    markdown = render_tasks_markdown(profile.name, tasks, project_names)
    return PlainTextResponse(content=markdown, media_type="text/markdown")


@router.put("/sort", summary="Reorder tasks")
async def sort_tasks(
    task_ids: list[int],  # Just IDs in desired order
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Reorder tasks by providing their IDs in the desired display order.

    - **task_ids**: List of task IDs in the order you want them displayed

    The first ID gets the lowest sort_order, the last the highest; tasks are
    displayed in ascending sort_order (with created_date as a tiebreak). This
    is used for drag-to-reorder among a set of siblings (e.g. one parent's
    subtasks); the caller is expected to pass a coherent sibling set, but the
    endpoint only enforces ownership, not shared parentage.
    """
    if not task_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_ids list cannot be empty",
        )

    if len(task_ids) != len(set(task_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate task IDs in request",
        )

    result = await db.execute(select(Task).filter(Task.id.in_(task_ids)))
    tasks = {t.id: t for t in result.scalars().all()}

    missing = set(task_ids) - set(tasks.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="One or more tasks not found"
        )

    # Authorize every distinct owning profile (403 if the caller owns none of
    # a given task's profile). One lookup per profile, not per task.
    for profile_id in {t.profile_id for t in tasks.values()}:
        await authorize_parent_profile(db, profile_id, current_user, "task")

    # Assign sort_order in request order (first item gets the lowest value).
    for order, task_id in enumerate(task_ids):
        tasks[task_id].sort_order = order

    await db.commit()
    return JSONResponse(content={"detail": "Tasks sorted successfully"})


@router.get("/{task_id}", summary="Get a task by ID")
async def read_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskRead:
    """
    Retrieve a specific task by its ID, including its computed urgency band
    and its subtask counts (subtask_count / subtask_done_count, done = status
    DONE only).

    - **task_id**: The unique identifier of the task to retrieve
    """
    task, _ = await _get_task_and_profile(db, task_id, current_user)
    subtask_counts = await _get_subtask_counts(db, parent_id=task_id)
    return _task_to_read(task, subtask_counts=subtask_counts)


@router.patch("/{task_id}", summary="Update a task (partial update)")
async def patch_task(
    task_id: int,
    task_update: TaskUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskRead:
    """
    Update specific fields of an existing task. Only provided fields will be updated.

    - **task_id**: The unique identifier of the task to update

    You can update any combination of these fields:
    - **profile_id**: Move the task to another profile (must belong to the same
      user; the task's project, if any, must belong to the new profile)
    - **title**: Title of the task
    - **notes**: Optional markdown notes about the task
    - **priority**: 0 none / 1 low / 2 medium / 3 high
    - **due_date**: Optional due date
    - **due_time**: Optional due time
    - **scheduled_date**: Optional date the task is scheduled for
    - **scheduled_time**: Optional time the task is scheduled for
    - **status**: Task status value. Entering done/cancelled stamps the
      closed date; reopening to any active status clears it
    - **block_reason**: Optional free-text reason when blocked
    - **external_ref**: Optional external reference (e.g. "ADO-2841")
    - **external_url**: Optional external URL
    - **project_id**: Optional project (must belong to the task's profile)
    - **parent_id**: Optional parent task (must belong to the task's
      resulting profile and must not itself be a subtask; a task that has
      subtasks cannot become a subtask; a task cannot be its own parent).
      Set null to detach a subtask from its parent

    Moving a task to another profile follows the same philosophy as
    project_id: the resulting parent is validated against the resulting
    profile, so moving a subtask fails (400) unless parent_id is nulled in
    the same request, and moving a task that has subtasks always fails (400)
    since its subtasks would be left behind.

    Scheduled data only lives on SCHEDULED tasks: if the resulting status (the
    new status if provided, else the existing one) is anything other than
    SCHEDULED, scheduled_date/scheduled_time are forced to null - even when the
    scheduled fields themselves were not part of this update (prevents orphaned
    scheduled data).
    """
    db_task, profile = await _get_task_and_profile(db, task_id, current_user)

    task_data = task_update.model_dump(exclude_unset=True)

    # Validate a profile move: new profile must belong to the same user, and
    # the task's project (if any) must belong to the new profile
    new_profile_id = task_data.get("profile_id")
    if new_profile_id is not None and new_profile_id != db_task.profile_id:
        new_profile = await db.get(Profile, new_profile_id)
        if not new_profile or new_profile.user_id != profile.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New profile not found or does not belong to the same user",
            )
    target_profile_id = (
        new_profile_id if new_profile_id is not None else db_task.profile_id
    )

    # Validate the resulting project (moved or kept) against the resulting profile
    target_project_id = (
        task_data["project_id"] if "project_id" in task_data else db_task.project_id
    )
    if target_project_id is not None:
        project = await db.get(Project, target_project_id)
        if not project or project.profile_id != target_profile_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project not found or does not belong to the task's profile",
            )

    # A profile move may not leave subtasks behind: a task that has subtasks
    # cannot move (mirrors the project rule - profile coherence is enforced,
    # never silently fixed)
    if new_profile_id is not None and new_profile_id != db_task.profile_id:
        subtask_total = await db.scalar(
            select(func.count(Task.id)).filter(Task.parent_id == task_id)
        )
        if subtask_total:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move a task with subtasks to another profile",
            )

    # Validate the resulting parent (moved or kept) against the resulting
    # profile - so moving a subtask to another profile fails unless parent_id
    # is nulled in the same request
    target_parent_id = (
        task_data["parent_id"] if "parent_id" in task_data else db_task.parent_id
    )
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
        if "parent_id" in task_data:
            subtask_total = await db.scalar(
                select(func.count(Task.id)).filter(Task.parent_id == task_id)
            )
            if subtask_total:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A task with subtasks cannot itself become a subtask",
                )

    # Status transitions: entering done/cancelled stamps closed_date (unless
    # already closed); leaving them for an active status clears it
    if "status" in task_data:
        new_status = task_data["status"]
        if new_status in CLOSED_STATUSES:
            if db_task.status not in CLOSED_STATUSES:
                db_task.closed_date = datetime.now()
        elif db_task.status in CLOSED_STATUSES:
            db_task.closed_date = None

    for key, value in task_data.items():
        setattr(db_task, key, value)

    # Scheduled data only lives on SCHEDULED tasks; any other resulting status
    # forces the scheduled fields null (prevents orphaned scheduled data). This
    # fires both when status changes away from SCHEDULED and when the task was
    # never scheduled, regardless of whether the scheduled fields were sent
    resulting_status = task_data.get("status", db_task.status)
    if resulting_status != TaskStatus.SCHEDULED:
        db_task.scheduled_date = None
        db_task.scheduled_time = None

    db_task.updated_date = datetime.now()  # server-stamped, never client-set
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task change violates a database constraint",
        )
    await db.refresh(db_task)
    subtask_counts = await _get_subtask_counts(db, parent_id=task_id)
    return _task_to_read(db_task, subtask_counts=subtask_counts)


@router.delete("/{task_id}", summary="Delete a task")
async def delete_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a task by its ID.

    - **task_id**: The unique identifier of the task to delete

    Deleting a parent task also deletes all of its subtasks (database-level
    ON DELETE CASCADE). This action cannot be undone.
    """
    db_task, _ = await _get_task_and_profile(db, task_id, current_user)

    await db.delete(db_task)
    await db.commit()
    return JSONResponse(content={"detail": "Task deleted successfully"})
