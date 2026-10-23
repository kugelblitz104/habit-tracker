from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.dependencies import (
    authorize_parent_profile,
    get_current_user,
    get_db,
    get_owned_profile,
    resolve_habit_profile_id,
    resolve_today,
)
from habit_tracker.core.http import bulk_delete_in_profile, validate_sort_ids
from habit_tracker.core.slugs import allocate_slug, get_by_slug
from habit_tracker.models import HabitCreate, HabitList, HabitRead
from habit_tracker.schemas.db_models import Habit, Tracker, User
from habit_tracker.services.habits import habit_to_read
from habit_tracker.services.notifications import HABIT, reschedule

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new habit")
async def create_habit(
    habit: HabitCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HabitRead:
    """
    Create a new habit with the following information:

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
    - **profile_id**: The profile this habit belongs to. Must belong to the
      current user

    The response carries a server-assigned **slug** derived from the name and
    unique within the profile ("Stretch" twice gives `stretch` then
    `stretch-2`), for use as a readable detail URL - see
    `GET /habits/by-slug/{slug}`. It cannot be set by the client.
    """
    profile_id = await resolve_habit_profile_id(db, current_user.id, habit.profile_id)
    db_habit = Habit(
        **habit.model_dump(exclude={"profile_id"}),
        profile_id=profile_id,
    )
    db_habit.slug = await allocate_slug(
        db, Habit, profile_id=profile_id, source=habit.name
    )
    db.add(db_habit)
    await reschedule(db, HABIT, db_habit)
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

    - **habit_ids**: List of habit IDs in the order you want them displayed,
      naming only habits the caller owns

    The first ID gets the lowest sort_order, last ID gets the highest.
    Habits are displayed in ascending sort_order. sort_order gaps are
    preserved for archived habits within the affected profiles.

    Any unknown id is reported as 404 before ownership of the touched
    profiles is checked, so a batch mixing an unknown id with a foreign
    habit reports the unknown id rather than a 403.
    """
    validate_sort_ids(habit_ids, noun="habit")

    requested_result = await db.execute(select(Habit).filter(Habit.id.in_(habit_ids)))
    requested = {h.id: h for h in requested_result.scalars().all()}

    missing_habits = set(habit_ids) - set(requested.keys())
    if missing_habits:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="One or more habits not found"
        )

    # Authorize every distinct owning profile (403 if the caller owns none of
    # a given habit's profile). One lookup per profile, not per habit.
    profile_ids = {h.profile_id for h in requested.values()}
    for profile_id in profile_ids:
        await authorize_parent_profile(db, profile_id, current_user, "habit")

    # Archived habits in the touched profiles keep their sort_order slots, so
    # reordering the visible habits never renumbers over an archived one.
    siblings_result = await db.execute(
        select(Habit).filter(Habit.profile_id.in_(profile_ids))
    )
    archived_sort_orders = {
        h.sort_order
        for h in siblings_result.scalars().all()
        if h.archived and h.id not in habit_ids
    }

    # Assign sort_order (first item gets lowest value)
    current_sort_order = 0
    for habit_id in habit_ids:
        if not requested[habit_id].archived:
            # Skip any sort_order values taken by archived habits
            while current_sort_order in archived_sort_orders:
                current_sort_order += 1
            requested[habit_id].sort_order = current_sort_order
            current_sort_order += 1

    await db.commit()
    return JSONResponse(content={"detail": "Habits sorted successfully"})


@router.get("/", summary="List habits for a profile")
async def list_habits(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose habits to list"),
    limit: int = Query(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of habits to return (1-100)",
    ),
    tz: str | None = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "'today' for completed_today/skipped_today is today in this "
            "zone; when omitted, the server's local date is used."
        ),
    ),
    offset: int = Query(default=0, ge=0, description="Number of habits to skip"),
) -> HabitList:
    """
    Get a paginated list of habits belonging to a profile.

    - **profile_id**: The profile whose habits to list (required)
    - **limit**: Maximum number of habits to return (default: 5, max: 100)
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    - **offset**: Number of habits to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "habit")

    # sort_order is the UI's display order; id breaks ties among habits that
    # have never been reordered (sort_order defaults to 0 for all of them).
    result = await db.execute(
        select(Habit)
        .filter(Habit.profile_id == profile_id)
        .order_by(Habit.sort_order, Habit.id)
        .limit(limit)
        .offset(offset)
    )
    db_habits = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(Habit.profile_id == profile_id)
    )
    total = count_result.scalar() or 0

    today = resolve_today(tz)
    habit_ids = [h.id for h in db_habits]

    today_trackers = {}
    if habit_ids:
        tracker_result = await db.execute(
            select(Tracker).filter(
                Tracker.habit_id.in_(habit_ids), Tracker.dated == today
            )
        )
        for tracker in tracker_result.scalars().all():
            today_trackers[tracker.habit_id] = tracker

    habits_read = []
    for habit in db_habits:
        habit_read = HabitRead.model_validate(habit)
        tracker = today_trackers.get(habit.id)
        habit_read.completed_today = (
            tracker.status == TrackerStatus.COMPLETED if tracker else False
        )
        habit_read.skipped_today = (
            tracker.status == TrackerStatus.SKIPPED if tracker else False
        )
        habits_read.append(habit_read)

    return HabitList(
        habits=habits_read,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/by-slug/{slug}", summary="Get a habit by its URL slug")
async def read_habit_by_slug(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile the slug belongs to"),
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
    Retrieve a habit by its URL **slug** instead of its numeric id, so a habit
    URL can read as the habit it opens (`/habits/daily-stretch`). The response
    is identical to `GET /habits/{habit_id}`.

    - **slug**: The habit's slug, as returned in **slug** on any habit read
    - **profile_id**: The profile the slug belongs to (required)
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)

    Slugs are unique per profile and are re-derived when a habit's name changes,
    so a slug that resolved before a rename returns 404 afterwards - the numeric
    route is the stable one.
    """
    await get_owned_profile(db, profile_id, current_user, "habit")

    habit = await get_by_slug(db, Habit, profile_id=profile_id, slug=slug)
    if habit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
        )

    return await habit_to_read(db, habit, tz)


@router.delete("/", summary="Delete all habits in a profile")
async def delete_all_habits(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose habits to delete"),
) -> JSONResponse:
    """
    Delete every habit (and its trackers) in a profile.

    - **profile_id**: The profile whose habits to delete (required)

    This action cannot be undone. Each habit's tracker history is deleted
    with it (ON DELETE CASCADE).
    """
    return await bulk_delete_in_profile(
        db,
        Habit,
        profile_id,
        current_user,
        resource_name="habit",
        detail="Deleted {count} habits and their trackers",
    )
