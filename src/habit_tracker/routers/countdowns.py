from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models import (
    CountdownCreate,
    CountdownList,
    CountdownRead,
    CountdownUpdate,
)
from habit_tracker.schemas.db_models import Countdown, Task, User

router = APIRouter(
    prefix="/countdowns",
    tags=["countdowns"],
    responses={404: {"description": "Not found"}},
)


async def _validate_task_link(
    db: AsyncSession, task_id: int | None, profile_id: int
) -> None:
    """When a countdown links a task, that task must belong to the same profile."""
    if task_id is None:
        return
    task = await db.get(Task, task_id)
    if not task or task.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linked task not found or belongs to a different profile",
        )


async def _get_countdown_and_authorize(
    db: AsyncSession, countdown_id: int, current_user: User
) -> Countdown:
    countdown = await db.get(Countdown, countdown_id)
    if not countdown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Countdown not found"
        )
    await authorize_parent_profile(
        db, countdown.profile_id, current_user, "countdown"
    )
    return countdown


@router.get("/", summary="List countdowns for a profile")
async def list_countdowns(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose countdowns to list"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CountdownList:
    """List a profile's countdowns, soonest target first."""
    await get_owned_profile(db, profile_id, current_user, "countdown")

    query = select(Countdown).filter(Countdown.profile_id == profile_id)
    result = await db.execute(
        query.order_by(Countdown.target_date, Countdown.target_time)
        .limit(limit)
        .offset(offset)
    )
    countdowns = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(Countdown.profile_id == profile_id)
    )
    total = count_result.scalar() or 0

    return CountdownList(
        countdowns=[CountdownRead.model_validate(c) for c in countdowns],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a countdown")
async def create_countdown(
    countdown: CountdownCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownRead:
    """Create a countdown. `task_id` is optional; when set it must reference a
    task in the same profile."""
    await get_owned_profile(db, countdown.profile_id, current_user, "countdown")
    await _validate_task_link(db, countdown.task_id, countdown.profile_id)

    db_countdown = Countdown(**countdown.model_dump())
    db.add(db_countdown)
    await db.commit()
    await db.refresh(db_countdown)
    return CountdownRead.model_validate(db_countdown)


@router.get("/{countdown_id}", summary="Get a countdown by ID")
async def read_countdown(
    countdown_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownRead:
    countdown = await _get_countdown_and_authorize(db, countdown_id, current_user)
    return CountdownRead.model_validate(countdown)


@router.patch("/{countdown_id}", summary="Update a countdown (partial update)")
async def patch_countdown(
    countdown_id: int,
    countdown_update: CountdownUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownRead:
    db_countdown = await _get_countdown_and_authorize(db, countdown_id, current_user)

    data = countdown_update.model_dump(exclude_unset=True)
    # Re-validate the task link whenever profile or task changes.
    if "task_id" in data or "profile_id" in data:
        await _validate_task_link(
            db,
            data.get("task_id", db_countdown.task_id),
            data.get("profile_id", db_countdown.profile_id),
        )

    for key, value in data.items():
        setattr(db_countdown, key, value)
    db_countdown.updated_date = datetime.now()  # server-stamped, never client-set
    await db.commit()
    await db.refresh(db_countdown)
    return CountdownRead.model_validate(db_countdown)


@router.delete("/{countdown_id}", summary="Delete a countdown")
async def delete_countdown(
    countdown_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    db_countdown = await _get_countdown_and_authorize(db, countdown_id, current_user)
    await db.delete(db_countdown)
    await db.commit()
    return JSONResponse(content={"detail": "Countdown deleted successfully"})
