from datetime import date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_habit,
    resolve_timezone,
    resolve_today,
)
from habit_tracker.models import (
    Habit,
    HabitCreate,
    HabitKPIs,
    HabitRead,
    HabitStreak,
    HabitUpdate,
    Profile,
    Tracker,
    TrackerList,
    TrackerLite,
    TrackerLiteList,
    TrackerRead,
)
from habit_tracker.schemas.db_models import User
from habit_tracker.services.habit_stats import calculate_kpis, calculate_streaks

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


async def _resolve_habit_profile_id(
    db: AsyncSession, owner_user_id: int, profile_id: Optional[int]
) -> int:
    """Resolve the profile a habit should belong to.

    owner_user_id is the id of the user who owns (or will own) the habit. If
    profile_id is given, it must exist and belong to that owner (400
    otherwise) - this keeps the habit's user_id/profile_id invariant intact
    even when an admin edits another user's habit. If omitted, the owner's
    oldest profile is used for back-compat.
    """
    if profile_id is not None:
        profile = await db.get(Profile, profile_id)
        if not profile or profile.user_id != owner_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile not found or does not belong to the habit's owner",
            )
        return profile_id

    result = await db.execute(
        select(Profile)
        .filter(Profile.user_id == owner_user_id)
        .order_by(Profile.created_date, Profile.id)
        .limit(1)
    )
    default_profile = result.scalar_one_or_none()
    if not default_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no profiles; create a profile first",
        )
    return default_profile.id


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new habit")
async def create_habit(
    habit: HabitCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HabitRead:
    """
    Create a new habit with the following information:

    - **user_id**: The ID of the user who owns this habit
    - **name**: Name of the habit
    - **question**: The daily question to prompt for this habit
    - **color**: Color code for visual representation
    - **frequency**: How many times the habit should be completed within the range
    - **range**: The number of days within which the frequency should be met
    - **reminder**: Whether to enable reminders for this habit
    - **notes**: Optional additional notes about the habit
    - **archived**: Whether the habit is archived
    - **sort_order**: The order in which the habit appears in lists (ascending)
    - **category**: Optional free-text group label (e.g. "Hygiene")
    - **profile_id**: Optional profile for this habit. Must belong to the
      current user; defaults to the user's oldest profile if omitted
    """
    profile_id = await _resolve_habit_profile_id(db, current_user.id, habit.profile_id)
    db_habit = Habit(
        **habit.model_dump(exclude={"profile_id"}),
        profile_id=profile_id,
        user_id=current_user.id,
    )
    db.add(db_habit)
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.put("/sort", summary="Reorder habits")
async def sort_habits(
    habit_ids: list[int],  # Just IDs in desired order
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Reorder habits by providing their IDs in the desired display order.

    - **habit_ids**: List of habit IDs in the order you want them displayed

    The first ID gets the lowest sort_order, last ID gets the highest.
    Habits are displayed in ascending sort_order.
    """
    # Validate input
    if not habit_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="habit_ids list cannot be empty",
        )

    if len(habit_ids) != len(set(habit_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate habit IDs in request",
        )

    # Fetch ALL user's habits
    all_habits_result = await db.execute(
        select(Habit).filter(Habit.user_id == current_user.id)
    )
    all_habits = {h.id: h for h in all_habits_result.scalars().all()}

    # Check if all requested habits exist and belong to user
    missing_habits = set(habit_ids) - set(all_habits.keys())
    if missing_habits:
        # Check if they exist at all (404) or just don't belong to user (403)
        exists_check = await db.execute(
            select(Habit.id).filter(Habit.id.in_(missing_habits))
        )
        if exists_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to sort one or more of these habits",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="One or more habits not found"
        )

    # Collect sort_order values of archived habits not being sorted
    archived_sort_orders = {
        h.sort_order
        for h in all_habits.values()
        if h.archived and h.id not in habit_ids
    }

    # Assign sort_order (first item gets lowest value)
    current_sort_order = 0
    for habit_id in habit_ids:
        if not all_habits[habit_id].archived:
            # Skip any sort_order values taken by archived habits
            while current_sort_order in archived_sort_orders:
                current_sort_order += 1
            all_habits[habit_id].sort_order = current_sort_order
            current_sort_order += 1

    await db.commit()
    return JSONResponse(content={"detail": "Habits sorted successfully"})


@router.get("/{habit_id}", summary="Get a habit by ID")
async def read_habit(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: Optional[str] = Query(
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
    habit = await get_owned_habit(db, habit_id, current_user)
    habit_read: HabitRead = HabitRead.model_validate(habit)
    today = resolve_today(tz)
    today_tracker = (
        await db.execute(
            select(Tracker)
            .filter(Tracker.habit_id == habit_id, Tracker.dated == today)
            .limit(1)
        )
    ).scalar()

    habit_read.completed_today = today_tracker.status == 2 if today_tracker else False
    habit_read.skipped_today = today_tracker.status == 1 if today_tracker else False

    return habit_read


@router.get("/{habit_id}/trackers", summary="List all trackers for a habit")
async def list_habit_trackers(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(
        default=5,
        ge=1,
        le=1000,
        description="Maximum number of trackers to return (1-1000)",
    ),
) -> TrackerList:
    """
    Get all tracker entries for a specific habit, ordered by date (most recent first).

    - **habit_id**: The unique identifier of the habit
    - **limit**: Maximum number of trackers to return (default: 5, max: 1000)

    Returns tracker entries showing completion/skip status for each date.
    """
    await get_owned_habit(db, habit_id, current_user)

    result = await db.execute(
        select(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .order_by(Tracker.dated.desc())
        .limit(limit)  # ge=1 validation guarantees a positive limit
    )
    db_trackers = result.scalars().all()

    return TrackerList(
        trackers=[TrackerRead.model_validate(t) for t in db_trackers],
        total=len(db_trackers),
        limit=limit,
        offset=0,
    )


@router.get("/{habit_id}/trackers/lite", summary="List trackers in lightweight format")
async def list_habit_trackers_lite(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    end_date: Optional[date] = Query(
        default=None,
        description="End date for the date range (defaults to today). Format: YYYY-MM-DD",
    ),
    days: int = Query(
        default=42,
        ge=1,
        le=3660,
        description="Number of days to fetch (1-3660, default: 42 = 6 weeks)",
    ),
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "the default end_date is today in this zone; when omitted, the "
            "server's local date is used."
        ),
    ),
) -> TrackerLiteList:
    """
    Get tracker entries in a lightweight format with date-based pagination.

    This endpoint returns only the essential fields:
    - id: Tracker ID (for fetching full details if needed)
    - dated: The date of the tracker entry
    - status: 0=not completed, 1=skipped, 2=completed
    - has_note: Whether this tracker has a note attached

    Use this for calendar views and streak calculations. Use the full trackers
    endpoint or fetch individual trackers when you need notes or timestamps.

    - **habit_id**: The unique identifier of the habit
    - **end_date**: End date for the range (defaults to today)
    - **days**: Number of days to fetch (1-3660, default: 42 = 6 weeks)
    - **tz**: Optional IANA timezone for the default end_date (invalid name -> 422)
    """
    await get_owned_habit(db, habit_id, current_user)

    # Validate tz even when end_date is explicit so a typo never passes
    # silently
    zone = resolve_timezone(tz)

    # Default end_date to today if not provided; datetime.now(None) is
    # server-local time, so a missing tz keeps the legacy behavior
    if end_date is None:
        end_date = datetime.now(zone).date()

    # Calculate start date
    start_date = end_date - timedelta(days=days - 1)

    # Query trackers within the date range
    result = await db.execute(
        select(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .filter(Tracker.dated >= start_date)
        .filter(Tracker.dated <= end_date)
        .order_by(Tracker.dated.desc())
    )
    db_trackers = result.scalars().all()

    # Check if there are older trackers (for has_previous flag)
    older_result = await db.execute(
        select(Tracker.id)
        .filter(Tracker.habit_id == habit_id)
        .filter(Tracker.dated < start_date)
        .limit(1)
    )
    has_previous = older_result.scalar() is not None

    # Convert to lite format with has_note flag
    trackers_lite = [
        TrackerLite(
            id=t.id,
            dated=t.dated,
            status=t.status,
            has_note=t.note is not None and t.note.strip() != "",
        )
        for t in db_trackers
    ]

    return TrackerLiteList(
        trackers=trackers_lite,
        total=len(trackers_lite),
        end_date=end_date,
        days=days,
        has_previous=has_previous,
    )


@router.get("/{habit_id}/kpis", summary="Get computed KPIs for a habit")
async def read_habit_kpis(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "KPIs are computed against today in this zone; when omitted, "
            "the server's local date is used."
        ),
    ),
) -> HabitKPIs:
    """
    Retrieve computed statistics for a habit.

    KPIs (streaks, completion rates, last completion, etc.) are derived from
    the habit's trackers on the fly - nothing is persisted. The computation
    mirrors the frontend so client and server agree.

    - **habit_id**: The unique identifier of the habit
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    """
    habit = await get_owned_habit(db, habit_id, current_user)

    result = await db.execute(
        select(Tracker).filter(Tracker.habit_id == habit_id)
    )
    trackers = result.scalars().all()

    today = resolve_today(tz)
    return calculate_kpis(habit, trackers, today)


@router.get("/{habit_id}/streaks", summary="List computed streaks for a habit")
async def read_habit_streaks(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "streaks are computed against today in this zone; when omitted, "
            "the server's local date is used."
        ),
    ),
) -> list[HabitStreak]:
    """
    Retrieve every streak for a habit, oldest first.

    A streak is an unbroken run of days that count toward the habit: days with
    an explicit completion or skip, or days that are auto-skipped (the
    frequency goal was already met within the range window). Derived from the
    habit's trackers on the fly - nothing is persisted.

    - **habit_id**: The unique identifier of the habit
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    """
    habit = await get_owned_habit(db, habit_id, current_user)

    result = await db.execute(
        select(Tracker).filter(Tracker.habit_id == habit_id)
    )
    trackers = result.scalars().all()

    today = resolve_today(tz)
    return calculate_streaks(
        trackers, habit.frequency, habit.range, habit.created_date, today
    )


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
    db_habit = await get_owned_habit(db, habit_id, current_user)
    habit_data = habit_update.model_dump()
    if habit_data.get("profile_id") is None:
        # Keep the habit's current profile - profile_id is never nulled
        habit_data.pop("profile_id", None)
    else:
        # Validate against the habit's owner, not the caller: an admin editing
        # another user's habit may only use that user's profiles
        habit_data["profile_id"] = await _resolve_habit_profile_id(
            db, db_habit.user_id, habit_data["profile_id"]
        )
    for key, value in habit_data.items():
        setattr(db_habit, key, value)
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
    - **notes**: Optional additional notes about the habit
    - **archived**: Whether the habit is archived
    - **sort_order**: The order in which the habit appears in lists (ascending)
    - **category**: Optional free-text group label (e.g. "Hygiene")
    - **profile_id**: Move the habit to another profile (must belong to the
      habit's owner)

    """
    db_habit = await get_owned_habit(db, habit_id, current_user)
    habit_data = habit_update.model_dump(exclude_unset=True)
    if habit_data.get("profile_id") is None:
        # Keep the habit's current profile - profile_id is never nulled
        habit_data.pop("profile_id", None)
    else:
        # Validate against the habit's owner, not the caller: an admin editing
        # another user's habit may only use that user's profiles
        habit_data["profile_id"] = await _resolve_habit_profile_id(
            db, db_habit.user_id, habit_data["profile_id"]
        )
    for key, value in habit_data.items():
        setattr(db_habit, key, value)
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
    db_habit = await get_owned_habit(db, habit_id, current_user)
    await db.delete(db_habit)
    await db.commit()
    return JSONResponse(content={"detail": "Habit deleted successfully"})
