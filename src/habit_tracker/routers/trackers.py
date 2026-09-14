from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_habit,
    get_owned_profile,
)
from habit_tracker.core.http import bulk_delete_in_profile, integrity_conflict
from habit_tracker.models import (
    TrackerCreate,
    TrackerList,
    TrackerRead,
    TrackerUpdate,
)
from habit_tracker.schemas.db_models import Habit, Tracker, User

router = APIRouter(
    prefix="/trackers", tags=["trackers"], responses={404: {"description": "Not found"}}
)


async def _get_owned_tracker(
    db: AsyncSession, tracker_id: int, current_user: User
) -> Tracker:
    """Fetch a tracker by ID (404 if missing) and verify its habit exists
    (404) and its owning profile belongs to the caller (403).

    Deliberately NOT folded into get_owned_child: a tracker reaches its
    profile indirectly through its habit, and raises a second 404
    ("Habit not found") that no other child-resource helper does.
    """
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
    await authorize_parent_profile(db, habit.profile_id, current_user, "tracker")
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
    except IntegrityError:
        await db.rollback()
        raise integrity_conflict("Tracker entry for this habit and date already exists")
    await db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.get("/", summary="List tracker entries for a profile")
async def list_trackers(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose trackers to list"),
    dated_from: date | None = Query(
        default=None, description="Only entries dated on or after this local date"
    ),
    dated_to: date | None = Query(
        default=None,
        description=(
            "Only entries dated on or before this local date. Inclusive, "
            "unlike the instant filters elsewhere: dated is a date, so one "
            "day is the same value in both bounds."
        ),
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of entries to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of entries to skip"),
) -> TrackerList:
    """
    Get a paginated list of tracker entries across every habit in a profile,
    most recent date first.

    The per-habit endpoints under /habits/{habit_id}/trackers answer "this
    habit's history"; this one answers "what was recorded over these days",
    which otherwise costs one request per habit.

    - **profile_id**: The profile whose trackers to list (required)
    - **dated_from**: Optional. Entries on or after this local date
    - **dated_to**: Optional. Entries on or before this local date
    - **limit**: Maximum number of entries to return (default: 100, max: 100)
    - **offset**: Number of entries to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "tracker")

    # A tracker has no profile_id of its own; it reaches one through its habit.
    filters = [Habit.profile_id == profile_id]
    if dated_from is not None:
        filters.append(Tracker.dated >= dated_from)
    if dated_to is not None:
        filters.append(Tracker.dated <= dated_to)

    scoped = select(Tracker).join(Habit, Tracker.habit_id == Habit.id).filter(*filters)

    count_result = await db.execute(
        select(func.count(Tracker.id))
        .select_from(Tracker)
        .join(Habit, Tracker.habit_id == Habit.id)
        .filter(*filters)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        scoped.order_by(Tracker.dated.desc(), Tracker.id).limit(limit).offset(offset)
    )

    return TrackerList(
        trackers=[TrackerRead.model_validate(t) for t in result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    db_tracker.updated_date = datetime.now()  # server-stamped, never client-set
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
    db_tracker.updated_date = datetime.now()  # server-stamped, never client-set
    await db.commit()
    await db.refresh(db_tracker)
    return TrackerRead.model_validate(db_tracker)


@router.delete("/", summary="Delete all trackers in a profile")
async def delete_all_trackers(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose trackers to delete"),
) -> JSONResponse:
    """
    Delete every tracker entry belonging to a profile's habits, keeping the
    habits themselves.

    - **profile_id**: The profile whose trackers to delete (required)

    This action cannot be undone.
    """
    habit_ids = select(Habit.id).where(Habit.profile_id == profile_id)
    return await bulk_delete_in_profile(
        db,
        Tracker,
        profile_id,
        current_user,
        resource_name="tracker",
        detail="Deleted {count} trackers",
        where=Tracker.habit_id.in_(habit_ids),
    )


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
