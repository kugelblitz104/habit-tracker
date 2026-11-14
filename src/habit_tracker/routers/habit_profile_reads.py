from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
    resolve_today,
)
from habit_tracker.models import HabitKPIsList, HabitTrackersLiteList
from habit_tracker.schemas.db_models import Tracker, User
from habit_tracker.services.habit_stats import calculate_kpis
from habit_tracker.services.habits import habit_page, habit_windows, window_bounds

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.get(
    "/trackers-lite",
    summary="List lightweight trackers for every habit in a profile",
)
async def list_habits_trackers_lite(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose habits to read"),
    end_date: date | None = Query(
        default=None, description="End date for the range (defaults to today)"
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
    archived: bool | None = Query(
        default=None,
        description="Filter by archived state. Omit to return both.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of habits to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of habits to skip"),
) -> HabitTrackersLiteList:
    """
    Get lightweight trackers over a date window for every habit in a profile.

    The per-habit endpoint under /habits/{habit_id}/trackers/lite answers
    "this habit's window"; this one answers "every habit's window", which
    otherwise costs one request per habit.

    Paging is over HABITS, not trackers: each entry carries every tracker in
    the window for its habit, so a caller can treat an entry exactly as it
    treats the per-habit response. Row volume is therefore bounded by
    days * limit, both of which the caller sets.

    - **profile_id**: The profile whose habits to read (required)
    - **end_date**: End date for the range (defaults to today)
    - **days**: Number of days to fetch (1-3660, default: 42 = 6 weeks)
    - **tz**: Optional IANA timezone for the default end_date (invalid name -> 422)
    - **archived**: Optional archived filter; omit for both
    - **limit**: Maximum number of habits to return (default: 100, max: 100)
    - **offset**: Number of habits to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "habit")
    start_date, end_date = window_bounds(end_date, days, tz)
    habits, total = await habit_page(
        db, profile_id, archived=archived, limit=limit, offset=offset
    )
    items = await habit_windows(db, habits, start_date, end_date)
    return HabitTrackersLiteList(items=items, total=total, limit=limit, offset=offset)


@router.get("/kpis", summary="Get computed KPIs for every habit in a profile")
async def list_habits_kpis(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose habits to read"),
    tz: str | None = Query(
        default=None,
        description=(
            "IANA timezone name (e.g. 'America/New_York'). When provided, "
            "KPIs are computed against today in this zone; when omitted, "
            "the server's local date is used."
        ),
    ),
    archived: bool | None = Query(
        default=None,
        description="Filter by archived state. Omit to return both.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of habits to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of habits to skip"),
) -> HabitKPIsList:
    """
    Retrieve computed statistics for every habit in a profile.

    The per-habit endpoint under /habits/{habit_id}/kpis answers "this
    habit's KPIs"; this one answers "every habit's", which otherwise costs
    one request and one full-history scan per habit.

    KPIs are derived from each habit's trackers on the fly - nothing is
    persisted - by the same calculate_kpis the per-habit endpoint uses.

    - **profile_id**: The profile whose habits to read (required)
    - **tz**: Optional IANA timezone for determining "today" (invalid name -> 422)
    - **archived**: Optional archived filter; omit for both
    - **limit**: Maximum number of habits to return (default: 100, max: 100)
    - **offset**: Number of habits to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "habit")

    # Validate tz even when there turn out to be no habits to compute KPIs
    # for, so a typo never passes silently.
    today = resolve_today(tz)

    habits, total = await habit_page(
        db, profile_id, archived=archived, limit=limit, offset=offset
    )
    habit_ids = [h.id for h in habits]
    if not habit_ids:
        return HabitKPIsList(items=[], total=total, limit=limit, offset=offset)

    # Full history for the page's habits in one query. Paging over habits is
    # what bounds this: only the requested page's history is loaded.
    rows = (
        (await db.execute(select(Tracker).filter(Tracker.habit_id.in_(habit_ids))))
        .scalars()
        .all()
    )
    trackers_by_habit: dict[int, list[Tracker]] = {hid: [] for hid in habit_ids}
    for tracker in rows:
        trackers_by_habit[tracker.habit_id].append(tracker)

    items = [
        calculate_kpis(habit, trackers_by_habit[habit.id], today) for habit in habits
    ]

    return HabitKPIsList(items=items, total=total, limit=limit, offset=offset)
