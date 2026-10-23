from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
    resolve_timezone,
    resolve_today,
)
from habit_tracker.models import (
    HabitKPIsList,
    HabitTrackersLite,
    HabitTrackersLiteList,
    TrackerLite,
)
from habit_tracker.schemas.db_models import Habit, Tracker, User
from habit_tracker.services.habit_stats import (
    auto_skip_lookback_start,
    auto_skipped_dates,
    calculate_kpis,
)
from habit_tracker.services.habits import TRACKER_LITE_COLUMNS

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

    # Validate tz even when end_date is explicit so a typo never passes
    # silently
    zone = resolve_timezone(tz)
    if end_date is None:
        end_date = datetime.now(zone).date()
    start_date = end_date - timedelta(days=days - 1)

    habit_filters = [Habit.profile_id == profile_id]
    if archived is not None:
        habit_filters.append(Habit.archived == archived)

    # sort_order is the UI's display order; id breaks ties among habits that
    # have never been reordered, which is what makes offset paging safe.
    habits = (
        (
            await db.execute(
                select(Habit)
                .filter(*habit_filters)
                .order_by(Habit.sort_order, Habit.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await db.execute(select(func.count()).select_from(Habit).filter(*habit_filters))
    ).scalar() or 0

    habit_ids = [h.id for h in habits]
    if not habit_ids:
        return HabitTrackersLiteList(items=[], total=total, limit=limit, offset=offset)

    in_window = (
        Tracker.habit_id.in_(habit_ids),
        Tracker.dated >= start_date,
        Tracker.dated <= end_date,
    )
    window_rows = (
        await db.execute(
            select(Tracker.habit_id, *TRACKER_LITE_COLUMNS)
            .filter(*in_window)
            .order_by(Tracker.dated.desc())
        )
    ).all()
    trackers_by_habit: dict[int, list[TrackerLite]] = {hid: [] for hid in habit_ids}
    for row in window_rows:
        trackers_by_habit[row.habit_id].append(TrackerLite.model_validate(row))

    habits_with_older = set(
        (
            await db.execute(
                select(Tracker.habit_id)
                .filter(Tracker.habit_id.in_(habit_ids), Tracker.dated < start_date)
                .distinct()
            )
        )
        .scalars()
        .all()
    )

    # One lookback query for the page, widened to the largest range on it.
    # Pulling extra completions for narrow-range habits is harmless:
    # auto_skipped_dates only ever reads [day - range + 1, day) for its own
    # habit, so the surplus is never counted.
    widest_range = max(h.range for h in habits)
    lookback_start = auto_skip_lookback_start(start_date, widest_range)
    completed_rows = (
        await db.execute(
            select(Tracker.habit_id, Tracker.dated).filter(
                Tracker.habit_id.in_(habit_ids),
                Tracker.dated >= lookback_start,
                Tracker.dated <= end_date,
                Tracker.status == TrackerStatus.COMPLETED,
            )
        )
    ).all()
    completed_by_habit: dict[int, set[date]] = {hid: set() for hid in habit_ids}
    for habit_id, dated in completed_rows:
        completed_by_habit[habit_id].add(dated)

    items = [
        HabitTrackersLite(
            habit_id=habit.id,
            trackers=trackers_by_habit[habit.id],
            end_date=end_date,
            days=days,
            has_previous=habit.id in habits_with_older,
            auto_skipped_dates=auto_skipped_dates(
                start_date,
                end_date,
                completed_by_habit[habit.id],
                habit.frequency,
                habit.range,
            ),
        )
        for habit in habits
    ]

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

    habit_filters = [Habit.profile_id == profile_id]
    if archived is not None:
        habit_filters.append(Habit.archived == archived)

    habits = (
        (
            await db.execute(
                select(Habit)
                .filter(*habit_filters)
                .order_by(Habit.sort_order, Habit.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await db.execute(select(func.count()).select_from(Habit).filter(*habit_filters))
    ).scalar() or 0

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
