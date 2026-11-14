from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_habit,
    resolve_today,
)
from habit_tracker.core.route_helpers import paged
from habit_tracker.models import (
    HabitKPIs,
    HabitStreak,
    TrackerList,
    TrackerLiteList,
    TrackerRead,
)
from habit_tracker.schemas.db_models import Tracker, User
from habit_tracker.services.habit_stats import calculate_kpis, calculate_streaks
from habit_tracker.services.habits import habit_windows, window_bounds

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


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
    offset: int = Query(default=0, ge=0, description="Number of trackers to skip"),
) -> TrackerList:
    """
    Get all tracker entries for a specific habit, ordered by date (most recent first).

    - **habit_id**: The unique identifier of the habit
    - **limit**: Maximum number of trackers to return (default: 5, max: 1000)
    - **offset**: Number of trackers to skip (default: 0)

    Returns tracker entries showing completion/skip status for each date.
    """
    await get_owned_habit(db, habit_id, current_user)

    # dated is unique per habit (uix_habit_dated), so it alone is a total order.
    result, total = await paged(
        db,
        select(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .order_by(Tracker.dated.desc()),
        limit=limit,
        offset=offset,
    )
    db_trackers = result.scalars().all()

    return TrackerList(
        trackers=[TrackerRead.model_validate(t) for t in db_trackers],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{habit_id}/trackers/lite", summary="List lightweight trackers for one habit"
)
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
    limit: int = Query(
        default=1000,
        ge=1,
        le=1000,
        description="Maximum number of trackers to return (1-1000)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of trackers to skip"),
) -> TrackerLiteList:
    """
    Get one habit's tracker entries in a lightweight format with date-based
    pagination. For every habit in a profile in one request, use
    GET /habits/trackers-lite.

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
    - **limit**: Maximum number of trackers to return (1-1000, default: 1000)
    - **offset**: Number of trackers to skip (default: 0)
    """
    habit, _ = await get_owned_habit(db, habit_id, current_user)
    start_date, end_date = window_bounds(end_date, days, tz)
    (window,) = await habit_windows(
        db, [habit], start_date, end_date, limit=limit, offset=offset
    )

    # total counts the whole window, not the page
    count_result = await db.execute(
        select(func.count())
        .select_from(Tracker)
        .filter(
            Tracker.habit_id == habit_id,
            Tracker.dated >= start_date,
            Tracker.dated <= end_date,
        )
    )
    total = count_result.scalar() or 0

    return TrackerLiteList(
        trackers=window.trackers,
        total=total,
        end_date=end_date,
        days=days,
        has_previous=window.has_previous,
        auto_skipped_dates=window.auto_skipped_dates,
        limit=limit,
        offset=offset,
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
