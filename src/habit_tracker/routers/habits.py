from datetime import date, datetime, timedelta
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
    get_owned_habit,
    get_owned_profile,
    resolve_habit_profile_id,
    resolve_timezone,
    resolve_today,
)
from habit_tracker.core.http import bulk_delete_in_profile, validate_sort_ids
from habit_tracker.core.slugs import allocate_slug, get_by_slug
from habit_tracker.models import (
    HabitCreate,
    HabitKPIs,
    HabitList,
    HabitRead,
    HabitStreak,
    HabitUpdate,
    TrackerList,
    TrackerLite,
    TrackerLiteList,
    TrackerRead,
)
from habit_tracker.schemas.db_models import Habit, Profile, Tracker, User
from habit_tracker.services.habit_stats import (
    auto_skip_lookback_start,
    calculate_kpis,
    calculate_streaks,
    is_auto_skipped,
)

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
) -> HabitList:
    """
    Get a paginated list of habits belonging to a profile.

    - **profile_id**: The profile whose habits to list (required)
    - **limit**: Maximum number of habits to return (default: 5, max: 100)
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    """
    await get_owned_profile(db, profile_id, current_user, "habit")

    # sort_order is the UI's display order; id breaks ties among habits that
    # have never been reordered (sort_order defaults to 0 for all of them).
    result = await db.execute(
        select(Habit)
        .filter(Habit.profile_id == profile_id)
        .order_by(Habit.sort_order, Habit.id)
        .limit(limit)
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
        offset=0,
    )


async def _habit_to_read(db: AsyncSession, habit: Habit, tz: str | None) -> HabitRead:
    """A HabitRead with today's completed/skipped flags resolved in `tz`.

    Shared by the by-id and by-slug reads so the two cannot drift; the list
    endpoint computes the same flags in bulk for a whole page instead.
    """
    habit_read: HabitRead = HabitRead.model_validate(habit)
    today = resolve_today(tz)
    today_tracker = (
        await db.execute(
            select(Tracker)
            .filter(Tracker.habit_id == habit.id, Tracker.dated == today)
            .limit(1)
        )
    ).scalar()

    habit_read.completed_today = (
        today_tracker.status == TrackerStatus.COMPLETED if today_tracker else False
    )
    habit_read.skipped_today = (
        today_tracker.status == TrackerStatus.SKIPPED if today_tracker else False
    )
    return habit_read


# NOTE: must stay declared before GET /{habit_id}, per this router's
# static-paths-first convention.
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

    return await _habit_to_read(db, habit, tz)


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
    return await _habit_to_read(db, habit, tz)


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
    end_date: date | None = Query(
        default=None,
        description="End date for the date range (defaults to today). Format: YYYY-MM-DD",
    ),
    days: int = Query(
        default=42,
        ge=1,
        le=3660,
        description="Number of days to fetch (1-3660, default: 42 = 6 weeks)",
    ),
    tz: str | None = Query(
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

    Also returns **auto_skipped_dates** for the range, so callers can render a
    day's status without fetching extra history to evaluate auto-skip
    themselves.

    - **habit_id**: The unique identifier of the habit
    - **end_date**: End date for the range (defaults to today)
    - **days**: Number of days to fetch (1-3660, default: 42 = 6 weeks)
    - **tz**: Optional IANA timezone for the default end_date (invalid name -> 422)
    """
    habit, _ = await get_owned_habit(db, habit_id, current_user)

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

    # Auto-skip for a day looks back over [day - range + 1, day), so the oldest
    # day in this range needs completions from up to range - 1 days BEFORE
    # start_date. Querying that here is what lets callers fetch only the days
    # they actually render - the lookback never crosses the wire.
    lookback_start = auto_skip_lookback_start(start_date, habit.range)
    completed_result = await db.execute(
        select(Tracker.dated)
        .filter(Tracker.habit_id == habit_id)
        .filter(Tracker.dated >= lookback_start)
        .filter(Tracker.dated <= end_date)
        .filter(Tracker.status == TrackerStatus.COMPLETED)
    )
    completed_dates = set(completed_result.scalars().all())

    auto_skipped_dates = [
        day
        for day in (
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        )
        if is_auto_skipped(day, completed_dates, habit.frequency, habit.range)
    ]

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
        auto_skipped_dates=auto_skipped_dates,
    )


@router.get("/{habit_id}/kpis", summary="Get computed KPIs for a habit")
async def read_habit_kpis(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: str | None = Query(
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
    habit, _ = await get_owned_habit(db, habit_id, current_user)

    result = await db.execute(select(Tracker).filter(Tracker.habit_id == habit_id))
    trackers = result.scalars().all()

    today = resolve_today(tz)
    return calculate_kpis(habit, trackers, today)


@router.get("/{habit_id}/streaks", summary="List computed streaks for a habit")
async def read_habit_streaks(
    habit_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    tz: str | None = Query(
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
    habit, _ = await get_owned_habit(db, habit_id, current_user)

    result = await db.execute(select(Tracker).filter(Tracker.habit_id == habit_id))
    trackers = result.scalars().all()

    today = resolve_today(tz)
    return calculate_streaks(
        trackers, habit.frequency, habit.range, habit.created_date, today
    )


async def _apply_habit_update(
    db: AsyncSession, db_habit: Habit, profile: Profile, habit_data: dict
) -> None:
    """Apply an update dict to a habit - shared by PUT (full model_dump) and
    PATCH (model_dump(exclude_unset=True)).

    profile_id is resolved against the habit's current owner (taken from the
    habit's owning profile), not the caller: an admin editing another user's
    habit may only use that user's profiles. A None/omitted profile_id keeps
    the habit's current profile - profile_id is never nulled.
    """
    if habit_data.get("profile_id") is None:
        habit_data.pop("profile_id", None)
    else:
        habit_data["profile_id"] = await resolve_habit_profile_id(
            db, profile.user_id, habit_data["profile_id"]
        )
    previous_name = db_habit.name
    previous_profile_id = db_habit.profile_id

    for key, value in habit_data.items():
        setattr(db_habit, key, value)

    # Re-slug when the name changes (the slug tracks the name, so renaming a
    # habit changes its URL and the old one stops resolving - the numeric URL
    # always keeps working). Also re-slug on a profile move, since slugs are
    # unique per profile and the clean slug may already be taken in the new one.
    # Here rather than in the two routes so PUT and PATCH cannot drift.
    if db_habit.name != previous_name or db_habit.profile_id != previous_profile_id:
        db_habit.slug = await allocate_slug(
            db,
            Habit,
            profile_id=db_habit.profile_id,
            source=db_habit.name,
            exclude_id=db_habit.id,
        )

    db_habit.updated_date = datetime.now()  # server-stamped, never client-set


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
    await _apply_habit_update(db, db_habit, profile, habit_update.model_dump())
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

    Changing the **name** re-derives the read-only **slug**, so the habit's
    `/habits/by-slug/{slug}` URL changes and the previous one stops resolving;
    the numeric id URL is unaffected. Moving the habit to another profile also
    re-derives it, since slugs are unique per profile.
    """
    db_habit, profile = await get_owned_habit(db, habit_id, current_user)
    await _apply_habit_update(
        db, db_habit, profile, habit_update.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


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
