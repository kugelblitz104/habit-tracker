from datetime import datetime
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TaskStatus
from habit_tracker.core.dependencies import (
    authorize_resource_access,
    get_current_user,
    get_db,
)
from habit_tracker.models import (
    Profile,
    Project,
    ProjectCreate,
    ProjectList,
    ProjectRead,
    ProjectUpdate,
    Task,
)
from habit_tracker.schemas.db_models import User

router = APIRouter(
    prefix="/projects", tags=["projects"], responses={404: {"description": "Not found"}}
)


async def _get_task_counts(
    db: AsyncSession, project_ids: Sequence[int]
) -> dict[int, tuple[int, int]]:
    """Return {project_id: (open_count, done_count)} for the given projects.

    open_count counts tasks whose status is neither DONE nor CANCELLED;
    done_count counts tasks with status DONE. Computed in a single grouped
    query to avoid N+1.
    """
    if not project_ids:
        return {}

    result = await db.execute(
        select(
            Task.project_id,
            func.sum(
                case(
                    (
                        Task.status.not_in(
                            [TaskStatus.DONE.value, TaskStatus.CANCELLED.value]
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((Task.status == TaskStatus.DONE.value, 1), else_=0)),
        )
        .filter(Task.project_id.in_(project_ids))
        .group_by(Task.project_id)
    )
    return {row[0]: (row[1] or 0, row[2] or 0) for row in result.all()}


def _project_to_read(
    project: Project, counts: dict[int, tuple[int, int]]
) -> ProjectRead:
    """Build a ProjectRead with open_count/done_count filled in."""
    project_read = ProjectRead.model_validate(project)
    open_count, done_count = counts.get(project.id, (0, 0))
    project_read.open_count = open_count
    project_read.done_count = done_count
    return project_read


@router.get("/", summary="List projects for a profile")
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose projects to list"),
    include_archived: bool = Query(
        default=False, description="Include archived projects in the results"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of projects to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of projects to skip"),
) -> ProjectList:
    """
    Get a paginated list of projects belonging to a profile, ordered by
    creation date. Each project includes **open_count** (tasks that are not
    done or cancelled) and **done_count** (tasks that are done) for progress
    display.

    - **profile_id**: The profile whose projects to list (required)
    - **include_archived**: Include archived projects (default: false)
    - **limit**: Maximum number of projects to return (default: 100, max: 100)
    - **offset**: Number of projects to skip (default: 0)
    """
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    authorize_resource_access(current_user, profile.user_id, "project")

    query = select(Project).filter(Project.profile_id == profile_id)
    count_query = select(func.count()).filter(Project.profile_id == profile_id)
    if not include_archived:
        query = query.filter(Project.archived.is_(False))
        count_query = count_query.filter(Project.archived.is_(False))

    result = await db.execute(
        query.order_by(Project.created_date).limit(limit).offset(offset)
    )
    db_projects = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    counts = await _get_task_counts(db, [p.id for p in db_projects])

    return ProjectList(
        projects=[_project_to_read(p, counts) for p in db_projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new project")
async def create_project(
    project: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProjectRead:
    """
    Create a new project with the following information:

    - **profile_id**: The ID of the profile this project belongs to
    - **name**: Name of the project
    - **color**: Hex color code for visual representation
    - **notes**: Optional markdown notes about the project
    - **archived**: Whether the project is archived
    """
    profile = await db.get(Profile, project.profile_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    authorize_resource_access(current_user, profile.user_id, "project")

    db_project = Project(**project.model_dump())
    db.add(db_project)
    await db.commit()
    await db.refresh(db_project)
    return _project_to_read(db_project, {})


@router.get("/{project_id}", summary="Get a project by ID")
async def read_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProjectRead:
    """
    Retrieve a specific project by its ID, including its task counts
    (**open_count** and **done_count**).

    - **project_id**: The unique identifier of the project to retrieve
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    profile = await db.get(Profile, project.profile_id)
    authorize_resource_access(current_user, profile.user_id, "project")

    counts = await _get_task_counts(db, [project.id])
    return _project_to_read(project, counts)


@router.patch("/{project_id}", summary="Update a project (partial update)")
async def patch_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProjectRead:
    """
    Update specific fields of an existing project. Only provided fields will be updated.

    - **project_id**: The unique identifier of the project to update

    You can update any combination of these fields:
    - **profile_id**: Move the project to another profile (must belong to the
      same user); the project's tasks move with it
    - **name**: Name of the project
    - **color**: Hex color code for visual representation
    - **notes**: Optional markdown notes about the project
    - **archived**: Whether the project is archived
    """
    db_project = await db.get(Project, project_id)
    if not db_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    profile = await db.get(Profile, db_project.profile_id)
    authorize_resource_access(current_user, profile.user_id, "project")

    project_data = project_update.model_dump(exclude_unset=True)

    new_profile_id = project_data.get("profile_id")
    if new_profile_id is not None and new_profile_id != db_project.profile_id:
        new_profile = await db.get(Profile, new_profile_id)
        if not new_profile or new_profile.user_id != profile.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New profile not found or does not belong to the same user",
            )
        # Move the project's tasks with it so they don't end up stranded in a
        # project that lives in a different profile (single UPDATE, no N+1)
        await db.execute(
            update(Task)
            .where(Task.project_id == db_project.id)
            .values(profile_id=new_profile_id)
        )

    for key, value in project_data.items():
        setattr(db_project, key, value)
    db_project.updated_date = datetime.now()  # server-stamped, never client-set
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project change violates a database constraint",
        )
    await db.refresh(db_project)

    counts = await _get_task_counts(db, [db_project.id])
    return _project_to_read(db_project, counts)


@router.delete("/{project_id}", summary="Delete a project")
async def delete_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a project by its ID.

    - **project_id**: The unique identifier of the project to delete

    This action cannot be undone. Tasks in the project are NOT deleted -
    they are kept and their project association is cleared.
    """
    db_project = await db.get(Project, project_id)
    if not db_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    profile = await db.get(Profile, db_project.profile_id)
    authorize_resource_access(current_user, profile.user_id, "project")

    await db.delete(db_project)  # tasks are kept; DB sets task.project_id to NULL
    await db.commit()
    return JSONResponse(
        content={
            "detail": "Project deleted successfully; its tasks were kept and unassigned"
        }
    )
