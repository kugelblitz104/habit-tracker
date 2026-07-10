from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
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


def _task_to_read(task: Task, today: date | None = None) -> TaskRead:
    """Build a TaskRead with its computed urgency band."""
    task_read = TaskRead.model_validate(task)
    task_read.band = compute_band(
        task.status,
        task.priority,
        task.due_date,
        scheduled_date=task.scheduled_date,
        today=today,
    )
    return task_read


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

    # Bands are date-relative and never stored, so band filtering happens in
    # Python after fetching; limit/offset apply to the band-filtered list
    today = date.today()
    tasks_read = [_task_to_read(t, today) for t in db_tasks]
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
    indented detail bullets for the fields that are set. Ordering matches the
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


@router.get("/{task_id}", summary="Get a task by ID")
async def read_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskRead:
    """
    Retrieve a specific task by its ID, including its computed urgency band.

    - **task_id**: The unique identifier of the task to retrieve
    """
    task, _ = await _get_task_and_profile(db, task_id, current_user)
    return _task_to_read(task)


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
    return _task_to_read(db_task)


@router.delete("/{task_id}", summary="Delete a task")
async def delete_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a task by its ID.

    - **task_id**: The unique identifier of the task to delete

    This action cannot be undone.
    """
    db_task, _ = await _get_task_and_profile(db, task_id, current_user)

    await db.delete(db_task)
    await db.commit()
    return JSONResponse(content={"detail": "Task deleted successfully"})
