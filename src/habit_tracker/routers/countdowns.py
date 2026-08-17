from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_child,
    get_owned_profile,
)
from habit_tracker.core.http import bulk_delete_in_profile, integrity_conflict
from habit_tracker.models import (
    CountdownCreate,
    CountdownList,
    CountdownRead,
    CountdownUpdate,
)
from habit_tracker.schemas.db_models import (
    Countdown,
    CountdownCategory,
    Profile,
    Task,
    User,
)
from habit_tracker.services.countdown_categories import find_or_create, get_in_profile

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


async def _resolve_category(
    db: AsyncSession,
    *,
    profile_id: int,
    category_id: int | None,
) -> int | None:
    """Validate a countdown's group selection against its own profile.

    A null `category_id` leaves the countdown uncategorised.
    """
    if category_id is None:
        return None
    category = await get_in_profile(db, profile_id=profile_id, category_id=category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category not found or does not belong to this profile",
        )
    return category.id


async def _get_countdown_and_profile(
    db: AsyncSession, countdown_id: int, current_user: User
) -> tuple[Countdown, Profile]:
    return await get_owned_child(
        db,
        Countdown,
        countdown_id,
        current_user,
        not_found_detail="Countdown not found",
        resource_name="countdown",
    )


@router.get("/", summary="List countdowns for a profile")
async def list_countdowns(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose countdowns to list"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    archived: bool = Query(
        default=False,
        description="True lists the archived countdowns instead of the live ones",
    ),
) -> CountdownList:
    """List a profile's countdowns, soonest target first. Archived countdowns are
    excluded unless `archived` is true, which lists those and only those."""
    await get_owned_profile(db, profile_id, current_user, "countdown")

    archived_filter = (
        Countdown.archived_date.is_not(None)
        if archived
        else Countdown.archived_date.is_(None)
    )
    query = select(Countdown).filter(
        Countdown.profile_id == profile_id, archived_filter
    )
    result = await db.execute(
        query.order_by(Countdown.target_date, Countdown.target_time)
        .limit(limit)
        .offset(offset)
    )
    countdowns = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(Countdown.profile_id == profile_id, archived_filter)
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
    task in the same profile. `category_id` files the countdown into an existing
    group, which must belong to the same profile; omit it to leave the countdown
    ungrouped. Create groups through `/countdown-categories/`."""
    await get_owned_profile(db, countdown.profile_id, current_user, "countdown")
    await _validate_task_link(db, countdown.task_id, countdown.profile_id)

    db_countdown = Countdown(**countdown.model_dump(exclude={"category_id"}))
    db_countdown.category_id = await _resolve_category(
        db, profile_id=countdown.profile_id, category_id=countdown.category_id
    )
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
    countdown, _ = await _get_countdown_and_profile(db, countdown_id, current_user)
    return CountdownRead.model_validate(countdown)


@router.patch("/{countdown_id}", summary="Update a countdown (partial update)")
async def patch_countdown(
    countdown_id: int,
    countdown_update: CountdownUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CountdownRead:
    """Update a countdown. `profile_id` moves it to another profile of the same
    user. `category_id` files it into an existing group in the same profile and a
    null clears the group. The group also re-resolves on a profile move, since a
    group belongs to one profile: it is recreated in the target profile under the
    same name. `archived` retires the countdown or restores it; the archive
    timestamp is server-stamped, and re-archiving keeps the original one."""
    db_countdown, profile = await _get_countdown_and_profile(
        db, countdown_id, current_user
    )

    data = countdown_update.model_dump(exclude_unset=True)

    # `archived` is a flag over a server-owned timestamp, so it never reaches the
    # setattr loop under its own name.
    if "archived" in data:
        archived = data.pop("archived")
        if not archived:
            data["archived_date"] = None
        elif db_countdown.archived_date is None:
            data["archived_date"] = datetime.now()

    new_profile_id = data.get("profile_id")
    if new_profile_id is not None and new_profile_id != db_countdown.profile_id:
        new_profile = await db.get(Profile, new_profile_id)
        if not new_profile or new_profile.user_id != profile.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New profile not found or does not belong to the same user",
            )

    # Re-validate the task link whenever profile or task changes.
    if "task_id" in data or "profile_id" in data:
        await _validate_task_link(
            db,
            data.get("task_id", db_countdown.task_id),
            data.get("profile_id", db_countdown.profile_id),
        )

    # Re-resolve the group whenever it is selected, and also on a profile move: a
    # group belongs to one profile, so keeping the old category_id would point the
    # countdown at a record in a profile it no longer belongs to.
    target_profile_id = data.get("profile_id", db_countdown.profile_id)
    try:
        if "category_id" in data:
            data["category_id"] = await _resolve_category(
                db,
                profile_id=target_profile_id,
                category_id=data["category_id"],
            )
        elif (
            "profile_id" in data
            and target_profile_id != db_countdown.profile_id
            and db_countdown.category_id is not None
        ):
            # find_or_create flushes a new category row, so its insert can collide
            # with a concurrent request naming the same new category.
            current = await db.get(CountdownCategory, db_countdown.category_id)
            data["category_id"] = (
                (
                    await find_or_create(
                        db, profile_id=target_profile_id, name=current.name
                    )
                ).id
                if current is not None
                else None
            )

        for key, value in data.items():
            setattr(db_countdown, key, value)
        db_countdown.updated_date = datetime.now()  # server-stamped, never client-set
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise integrity_conflict(
            "A countdown category with this name already exists in this profile"
        )
    await db.refresh(db_countdown)
    return CountdownRead.model_validate(db_countdown)


@router.delete("/", summary="Delete all countdowns in a profile")
async def delete_all_countdowns(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose countdowns to delete"),
) -> JSONResponse:
    """
    Delete every countdown in a profile.

    - **profile_id**: The profile whose countdowns to delete (required)

    This action cannot be undone. Linked tasks are not affected.
    """
    return await bulk_delete_in_profile(
        db,
        Countdown,
        profile_id,
        current_user,
        resource_name="countdown",
        detail="Deleted {count} countdowns",
    )


@router.delete("/{countdown_id}", summary="Delete a countdown")
async def delete_countdown(
    countdown_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    db_countdown, _ = await _get_countdown_and_profile(db, countdown_id, current_user)
    await db.delete(db_countdown)
    await db.commit()
    return JSONResponse(content={"detail": "Countdown deleted successfully"})
