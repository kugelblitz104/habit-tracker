from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.core.dependencies import resolve_habit_profile_id, resolve_today
from habit_tracker.core.route_helpers import paged
from habit_tracker.models import HabitRead, HabitTrackersLite, TrackerLite
from habit_tracker.schemas.db_models import Habit, Profile, Tracker
from habit_tracker.services.habit_stats import (
    auto_skip_lookback_start,
    auto_skipped_dates,
)
from habit_tracker.services.notifications import HABIT, reschedule
from habit_tracker.services.profile_moves import refresh_slug

# The columns a TrackerLite reads, so the lite reads skip whole ORM rows and
# never fetch note bodies. has_note: the note holds any non-whitespace character.
TRACKER_LITE_COLUMNS = (
    Tracker.id,
    Tracker.dated,
    Tracker.status,
    func.coalesce(Tracker.note.regexp_match(r"\S"), False).label("has_note"),
)


async def habit_page(
    db: AsyncSession,
    profile_id: int,
    *,
    archived: bool | None = None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Habit], int]:
    """One page of a profile's habits in display order, plus the match count.

    `archived` filters by archived state; None returns both.
    """
    habit_filters = [Habit.profile_id == profile_id]
    if archived is not None:
        habit_filters.append(Habit.archived == archived)

    # sort_order is the UI's display order; id breaks ties among habits that
    # have never been reordered, which is what makes offset paging safe.
    result, total = await paged(
        db,
        select(Habit).filter(*habit_filters).order_by(Habit.sort_order, Habit.id),
        limit=limit,
        offset=offset,
    )
    return result.scalars().all(), total


async def habits_to_read(
    db: AsyncSession, habits: Sequence[Habit], tz: str | None
) -> list[HabitRead]:
    """HabitReads with today's completed/skipped flags resolved in `tz`.

    One tracker query however many habits; none for an empty list, though
    `tz` is still validated so a typo never passes silently.
    """
    today = resolve_today(tz)
    today_status: dict[int, TrackerStatus] = {}
    if habits:
        rows = await db.execute(
            select(Tracker.habit_id, Tracker.status).filter(
                Tracker.habit_id.in_([h.id for h in habits]), Tracker.dated == today
            )
        )
        today_status = {habit_id: status for habit_id, status in rows.all()}

    reads = []
    for habit in habits:
        habit_read = HabitRead.model_validate(habit)
        status = today_status.get(habit.id)
        habit_read.completed_today = status == TrackerStatus.COMPLETED
        habit_read.skipped_today = status == TrackerStatus.SKIPPED
        reads.append(habit_read)
    return reads


async def habit_to_read(db: AsyncSession, habit: Habit, tz: str | None) -> HabitRead:
    """A HabitRead with today's completed/skipped flags resolved in `tz`.

    Used by the by-id and by-slug reads; the list endpoint reads a whole page
    through `habits_to_read`.
    """
    (habit_read,) = await habits_to_read(db, [habit], tz)
    return habit_read


def window_bounds(
    end_date: date | None, days: int, tz: str | None
) -> tuple[date, date]:
    """The inclusive `(start, end)` of a `days`-long window ending at `end_date`.

    `end_date` defaults to today in `tz` (server-local when `tz` is None).
    """
    # Validate tz even when end_date is explicit so a typo never passes
    # silently
    today = resolve_today(tz)
    end = today if end_date is None else end_date
    return end - timedelta(days=days - 1), end


async def habit_windows(
    db: AsyncSession,
    habits: Sequence[Habit],
    start_date: date,
    end_date: date,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> list[HabitTrackersLite]:
    """Each habit's lite trackers over `[start_date, end_date]`, in `habits` order.

    Three queries however many habits, none for an empty list. `limit` and
    `offset` page the tracker rows of all `habits` together, so they only make
    sense for one habit. `has_previous` and `auto_skipped_dates` describe the
    window and never depend on them.
    """
    if not habits:
        return []
    habit_ids = [h.id for h in habits]

    window_rows = (
        await db.execute(
            select(Tracker.habit_id, *TRACKER_LITE_COLUMNS)
            .filter(
                Tracker.habit_id.in_(habit_ids),
                Tracker.dated >= start_date,
                Tracker.dated <= end_date,
            )
            .order_by(Tracker.dated.desc())
            .limit(limit)
            .offset(offset)
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

    # Auto-skip for a day looks back over [day - range + 1, day), so the oldest
    # day in the window needs completions from up to range - 1 days BEFORE
    # start_date. Querying that here is what lets callers fetch only the days
    # they render; the lookback never crosses the wire. One query covers every
    # habit, widened to the largest range: auto_skipped_dates only reads its own
    # habit's [day - range + 1, day), so the surplus is never counted.
    lookback_start = auto_skip_lookback_start(start_date, max(h.range for h in habits))
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

    return [
        HabitTrackersLite(
            habit_id=habit.id,
            trackers=trackers_by_habit[habit.id],
            end_date=end_date,
            days=(end_date - start_date).days + 1,
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


async def apply_habit_update(
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
    # PUT dumps every field, so an omitted mask arrives as None; keep the stored
    # one (PATCH already rejects an explicit null).
    if habit_data.get("reminder_days") is None:
        habit_data.pop("reminder_days", None)
    previous_name = db_habit.name
    previous_profile_id = db_habit.profile_id

    for key, value in habit_data.items():
        setattr(db_habit, key, value)

    await refresh_slug(
        db,
        db_habit,
        source=db_habit.name,
        previous_source=previous_name,
        previous_profile_id=previous_profile_id,
    )

    db_habit.updated_date = utc_now()  # server-stamped, never client-set
    await reschedule(db, HABIT, db_habit)
