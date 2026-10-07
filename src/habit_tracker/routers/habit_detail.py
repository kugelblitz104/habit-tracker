from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_habit,
)
from habit_tracker.models import HabitRead, HabitUpdate
from habit_tracker.schemas.db_models import User
from habit_tracker.services.habits import apply_habit_update, habit_to_read

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.get("/{habit_id}", summary="Get a habit by ID")
async def read_habit(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: str | None = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "'today' for completed_today/skipped_today is today in this "
            "zone; when omitted, the server's local date is used."
        ),
    ),
) -> HabitRead:
    """
    Retrieve a specific habit by its ID.

    - **habit_id**: The unique identifier of the habit to retrieve
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    """
    habit, _ = await get_owned_habit(db, habit_id, current_user)
    return await habit_to_read(db, habit, tz)


@router.put("/{habit_id}", summary="Replace a habit (full update)")
async def update_habit(
    habit_id: int,
    habit_update: HabitUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HabitRead:
    """
    Replace all fields of an existing habit. All fields must be provided.

    This performs a full replacement of the habit resource.
    Use PATCH if you want to update only specific fields.

    - **habit_id**: The unique identifier of the habit to update
    """
    db_habit, profile = await get_owned_habit(db, habit_id, current_user)
    await apply_habit_update(db, db_habit, profile, habit_update.model_dump())
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.patch("/{habit_id}", summary="Update a habit (partial update)")
async def patch_habit(
    habit_id: int,
    habit_update: HabitUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HabitRead:
    """
    Update specific fields of an existing habit. Only provided fields will be updated.

    This performs a partial update of the habit resource.
    Use PUT if you want to replace the entire resource.

    - **habit_id**: The unique identifier of the habit to update

    You can update any combination of these fields:
    - **name**: Name of the habit
    - **question**: The daily question to prompt for this habit
    - **color**: Color code for visual representation
    - **frequency**: How many times the habit should be completed within the range
    - **range**: The number of days within which the frequency should be met
    - **reminder**: Whether to enable reminders for this habit
    - **reminder_time**: Optional wall-clock reminder time (HH:MM)
    - **reminder_days**: Weekday mask for the reminder, bit 0 = Monday ...
      bit 6 = Sunday, 1-127 (127 = every day)
    - **notes**: Optional additional notes about the habit
    - **archived**: Whether the habit is archived
    - **sort_order**: The order in which the habit appears in lists (ascending)
    - **category**: Optional free-text group label (e.g. "Hygiene")
    - **profile_id**: Move the habit to another profile (must belong to the
      habit's owner)

    Changing the **name** re-derives the read-only **slug**, so the habit's
    `/habits/by-slug/{slug}` URL changes and the previous one stops resolving;
    the numeric id URL is unaffected. Moving the habit to another profile also
    re-derives it, since slugs are unique per profile.
    """
    db_habit, profile = await get_owned_habit(db, habit_id, current_user)
    await apply_habit_update(
        db, db_habit, profile, habit_update.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.delete("/{habit_id}", summary="Delete a habit")
async def delete_habit(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a habit by its ID.

    - **habit_id**: The unique identifier of the habit to delete

    This action cannot be undone. All associated tracker entries will also be deleted.
    """
    db_habit, _ = await get_owned_habit(db, habit_id, current_user)
    await db.delete(db_habit)
    await db.commit()
    return JSONResponse(content={"detail": "Habit deleted successfully"})
