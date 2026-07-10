from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_resource_access,
    get_current_user,
    get_db,
    get_owned_habit,
)
from habit_tracker.models import (
    Habit,
    Tracker,
    TrackerCreate,
    TrackerRead,
    TrackerUpdate,
)
from habit_tracker.schemas.db_models import User

router = APIRouter(
    prefix="/trackers", tags=["trackers"], responses={404: {"description": "Not found"}}
)


async def _get_owned_tracker(
    db: AsyncSession, tracker_id: int, current_user: User
) -> Tracker:
    """Fetch a tracker by ID (404 if missing) and verify its habit exists
    (404) and belongs to the caller (403)."""
    tracker = await db.get(Tracker, tracker_id)
    if not tracker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracker not found"
        )
    habit = await db.get(Habit, tracker.habit_id)
    if not habit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
        )
    authorize_resource_access(current_user, habit.user_id, "tracker")
    return tracker


@router.post(
    "/", status_code=status.HTTP_201_CREATED, summary="Create a new tracker entry"
)
async def create_tracker(
    tracker: TrackerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TrackerRead:
    """
    Create a new tracker entry to record habit completion or skip for a specific date.

    - **habit_id**: The ID of the habit being tracked
    - **dated**: The date for this tracker entry
    - **status**: 0=not completed, 1=skipped, 2=completed
    - **note**: Optional note about this entry
    """
    # Verify the habit belongs to the current user
    await get_owned_habit(db, tracker.habit_id, current_user)

    db_tracker = Tracker(**tracker.model_dump())
    db.add(db_tracker)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracker entry for this habit and date already exists",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create tracker entry",
            )
    await db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.get("/{tracker_id}", summary="Get a tracker entry by ID")
async def read_tracker(
    tracker_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TrackerRead:
    """
    Retrieve a specific tracker entry by its ID.

    - **tracker_id**: The unique identifier of the tracker entry to retrieve
    """
    tracker = await _get_owned_tracker(db, tracker_id, current_user)
    return TrackerRead.model_validate(tracker)


@router.put("/{tracker_id}", summary="Replace a tracker entry (full update)")
async def update_tracker(
    tracker_id: int,
    tracker_update: TrackerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TrackerRead:
    """
    Replace all fields of an existing tracker entry. All fields must be provided.

    This performs a full replacement of the tracker resource.
    Use PATCH if you want to update only specific fields.

    - **tracker_id**: The unique identifier of the tracker entry to update
    """
    db_tracker = await _get_owned_tracker(db, tracker_id, current_user)

    tracker_data = tracker_update.model_dump()
    for key, value in tracker_data.items():
        setattr(db_tracker, key, value)
    await db.commit()
    await db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.patch("/{tracker_id}", summary="Update a tracker entry (partial update)")
async def patch_tracker(
    tracker_id: int,
    tracker_update: TrackerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TrackerRead:
    """
    Update specific fields of an existing tracker entry. Only provided fields will be updated.

    This performs a partial update of the tracker resource.
    Use PUT if you want to replace the entire resource.

    - **tracker_id**: The unique identifier of the tracker entry to update

    You can update any combination of these fields:
    - **dated**: The date for this tracker entry
    - **status**: 0=not completed, 1=skipped, 2=completed
    - **note**: Optional note about this entry
    """
    db_tracker = await _get_owned_tracker(db, tracker_id, current_user)

    tracker_data = tracker_update.model_dump(exclude_unset=True)
    for key, value in tracker_data.items():
        setattr(db_tracker, key, value)
    await db.commit()
    await db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.delete("/{tracker_id}", summary="Delete a tracker entry")
async def delete_tracker(
    tracker_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a tracker entry by its ID.

    - **tracker_id**: The unique identifier of the tracker entry to delete

    This action cannot be undone.
    """
    db_tracker = await _get_owned_tracker(db, tracker_id, current_user)

    await db.delete(db_tracker)
    await db.commit()
    return JSONResponse(
        content={"detail": "Tracker deleted successfully"},
        status_code=status.HTTP_200_OK,
    )
