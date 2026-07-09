"""Pure computation of habit KPIs and streaks from tracker data.

Ported from the frontend so the server and client agree on streak/KPI
semantics (the client computes the same values locally):

- ``src/features/trackers/utils/kpi-utils.ts``
  (``getEffectiveStartDate``, ``calculateStreaks``, ``getCurrentStreakLength``,
  ``calculateKPIsFromTrackers`` and its private helpers)
- ``src/features/trackers/utils/tracker-utils.tsx`` (``isAutoSkipped``)

Everything here is derived on the fly - nothing is persisted. The functions
take the habit, its trackers and ``today`` so they stay pure and unit-testable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from habit_tracker.constants import TrackerStatus
from habit_tracker.models.habits import HabitKPIs, HabitStreak
from habit_tracker.schemas.db_models import Habit, Tracker

# Number of trailing days used for the 30-day completion rate.
_THIRTY_DAYS = 30


def _as_date(value: date | datetime) -> date:
    """Coerce a habit's ``created_date`` (a datetime) to a plain date."""
    return value.date() if isinstance(value, datetime) else value


def get_effective_start_date(
    trackers: Iterable[Tracker], created_date: date | datetime
) -> date:
    """Return the earlier of the habit's created date or first tracker date.

    Only completed/skipped trackers count as "activity" - a lone
    not-completed row does not pull the start date earlier. Mirrors
    ``getEffectiveStartDate`` in the frontend.
    """
    created = _as_date(created_date)
    activity_dates = sorted(
        t.dated
        for t in trackers
        if t.dated is not None
        and t.status in (TrackerStatus.COMPLETED, TrackerStatus.SKIPPED)
    )
    first = activity_dates[0] if activity_dates else None
    return first if first is not None and first < created else created


def is_auto_skipped(
    day: date, completed_dates: set[date], frequency: int, range_: int
) -> bool:
    """Whether ``day`` is auto-skipped for a habit with this frequency/range.

    Auto-skip means the frequency goal was already met within the range
    window, so the user does not need to act on ``day`` to keep the streak.
    The window is ``[day - range + 1, day)`` and counts completions strictly
    before ``day`` (mirrors ``isAutoSkipped`` in the frontend).

    Daily habits (``frequency >= range``) are never auto-skipped.
    """
    if frequency >= range_:
        return False

    window_start = day - timedelta(days=range_ - 1)
    completions = 0
    cursor = window_start
    while cursor < day:
        if cursor in completed_dates:
            completions += 1
        cursor += timedelta(days=1)
    return completions >= frequency


def calculate_streaks(
    trackers: Iterable[Tracker],
    frequency: int,
    range_: int,
    created_date: date | datetime,
    today: date,
) -> list[HabitStreak]:
    """Compute every streak from the effective start date through today.

    A day continues a streak when it has an explicit completion or skip, or
    when it is auto-skipped. Returns streaks oldest-first (mirrors
    ``calculateStreaks`` in the frontend).
    """
    trackers = list(trackers)
    start = get_effective_start_date(trackers, created_date)
    completed_dates = {
        t.dated
        for t in trackers
        if t.status == TrackerStatus.COMPLETED and t.dated is not None
    }
    skipped_dates = {
        t.dated
        for t in trackers
        if t.status == TrackerStatus.SKIPPED and t.dated is not None
    }

    streaks: list[HabitStreak] = []
    current: dict | None = None
    day = start
    while day <= today:
        if day in completed_dates or day in skipped_dates:
            continues = True
        else:
            continues = is_auto_skipped(day, completed_dates, frequency, range_)

        if continues:
            if current is None:
                current = {"start": day, "end": day, "length": 1}
            else:
                current["end"] = day
                current["length"] += 1
        elif current is not None:
            streaks.append(
                HabitStreak(
                    start_date=current["start"],
                    end_date=current["end"],
                    length=current["length"],
                )
            )
            current = None
        day += timedelta(days=1)

    if current is not None:
        streaks.append(
            HabitStreak(
                start_date=current["start"],
                end_date=current["end"],
                length=current["length"],
            )
        )
    return streaks


def _current_streak_length(streaks: list[HabitStreak], today: date) -> int:
    """Length of the last streak, but only if it ends today (else 0)."""
    if not streaks:
        return 0
    last = streaks[-1]
    return last.length if last.end_date == today else 0


def _completion_rate(
    completed_dates: set[date],
    frequency: int,
    range_: int,
    window_start: date,
    today: date,
) -> float:
    """Completion rate (0.0-1.0) over ``[window_start, today]`` inclusive.

    Expected completions = ``window_days * frequency / range``; the rate is
    ``min(1.0, actual / expected)`` so an "N per M days" habit that hits its
    target reads as 100%. For a daily habit (frequency=1, range=1) this is
    simply ``completed_days / window_days``. Guards divide-by-zero -> 0.0.
    """
    window_days = (today - window_start).days + 1
    if window_days <= 0:
        return 0.0
    expected = window_days * frequency / range_
    if expected <= 0:
        return 0.0
    actual = sum(1 for d in completed_dates if window_start <= d <= today)
    return min(1.0, actual / expected)


def _weekday_completion_rates(
    completed_dates: set[date],
    frequency: int,
    range_: int,
    start: date,
    today: date,
) -> list[float]:
    """Per-weekday completion rates over the overall window.

    Returns a length-7 list indexed by ``date.weekday()`` (0 = Monday ...
    6 = Sunday). For each weekday the expected completions are spread evenly
    from the overall goal: ``day_count * frequency / range``.
    """
    totals = [0] * 7
    completed = [0] * 7
    day = start
    while day <= today:
        wd = day.weekday()
        totals[wd] += 1
        if day in completed_dates:
            completed[wd] += 1
        day += timedelta(days=1)

    rates: list[float] = []
    for wd in range(7):
        expected = totals[wd] * frequency / range_
        if expected <= 0:
            rates.append(0.0)
        else:
            rates.append(min(1.0, completed[wd] / expected))
    return rates


def calculate_kpis(habit: Habit, trackers: Iterable[Tracker], today: date) -> HabitKPIs:
    """Compute the full set of KPIs for a habit from its trackers."""
    trackers = list(trackers)
    frequency = habit.frequency
    range_ = habit.range

    completed_dates = {
        t.dated
        for t in trackers
        if t.status == TrackerStatus.COMPLETED and t.dated is not None
    }
    total_completions = sum(
        1 for t in trackers if t.status == TrackerStatus.COMPLETED
    )
    last_completed_date = max(completed_dates) if completed_dates else None

    streaks = calculate_streaks(
        trackers, frequency, range_, habit.created_date, today
    )
    current_streak = _current_streak_length(streaks, today)

    longest_streak = 0
    longest_streak_end_date: date | None = None
    for streak in streaks:
        # >= so the most recent streak wins ties (better for a recency label)
        if streak.length >= longest_streak:
            longest_streak = streak.length
            longest_streak_end_date = streak.end_date

    start = get_effective_start_date(trackers, habit.created_date)
    thirty_day_start = today - timedelta(days=_THIRTY_DAYS - 1)
    thirty_day_rate = _completion_rate(
        completed_dates, frequency, range_, thirty_day_start, today
    )
    overall_rate = _completion_rate(
        completed_dates, frequency, range_, start, today
    )
    weekday_rates = _weekday_completion_rates(
        completed_dates, frequency, range_, start, today
    )

    return HabitKPIs(
        total_completions=total_completions,
        current_streak=current_streak,
        longest_streak=longest_streak,
        longest_streak_end_date=longest_streak_end_date,
        thirty_day_completion_rate=thirty_day_rate,
        overall_completion_rate=overall_rate,
        last_completed_date=last_completed_date,
        weekday_completion_rates=weekday_rates,
    )
