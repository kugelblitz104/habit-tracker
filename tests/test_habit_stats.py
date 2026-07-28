"""Unit tests for the pure KPI math in ``services.habit_stats``.

These build Habit/Tracker instances in memory - no session, no API - so the
arithmetic can be pinned down exactly.
"""

from datetime import date, datetime

from habit_tracker.constants import TrackerStatus
from habit_tracker.schemas.db_models import Habit, Tracker
from habit_tracker.services.habit_stats import calculate_kpis

# A clean 4-week window: Mon 2026-01-05 through Sun 2026-02-01 gives exactly
# four of every weekday, so a weekday's completed share lands on a round 0.25.
START = date(2026, 1, 5)
TODAY = date(2026, 2, 1)

MON, TUE, WED, THU = 0, 1, 2, 3


def _habit(frequency: int, range_: int) -> Habit:
    return Habit(
        id=1,
        user_id=1,
        profile_id=1,
        name="Test",
        question="Did you?",
        color="#ffffff",
        frequency=frequency,
        range=range_,
        created_date=datetime(2026, 1, 5),
    )


def _tracker(day: date, status: int = TrackerStatus.COMPLETED) -> Tracker:
    return Tracker(id=int(day.strftime("%m%d")), habit_id=1, dated=day, status=status)


def _weekday_rates(habit: Habit, trackers: list[Tracker]) -> list[float]:
    return calculate_kpis(habit, trackers, TODAY).weekday_completion_rates


def test_weekday_rate_is_completed_share_not_goal_normalized():
    """A weekday's rate is completed/occurrences, NOT completed/expected.

    Normalizing by ``frequency / range`` scales every bar by ``range /
    frequency`` (7x here) and saturates at 1.0, which made a single stray
    Monday render as tall as a Wednesday completed every single week.
    """
    habit = _habit(frequency=1, range_=7)
    trackers = [
        _tracker(date(2026, 1, 7)),  # every Wednesday
        _tracker(date(2026, 1, 14)),
        _tracker(date(2026, 1, 21)),
        _tracker(date(2026, 1, 28)),
        _tracker(date(2026, 1, 5)),  # one stray Monday
    ]

    rates = _weekday_rates(habit, trackers)

    assert rates[WED] == 1.0  # 4 of 4
    assert rates[MON] == 0.25  # 1 of 4 - would be 1.0 under goal-normalization


def test_weekday_rate_ignores_skipped_and_auto_skipped_days():
    """Only COMPLETED counts. Explicit skips and auto-skips contribute zero.

    With frequency=1/range=7, the Wednesday completions auto-skip the rest of
    each week - those days must not inflate their weekday's bar.
    """
    habit = _habit(frequency=1, range_=7)
    trackers = [
        _tracker(date(2026, 1, 7)),  # Wednesdays: completed
        _tracker(date(2026, 1, 14)),
        _tracker(date(2026, 1, 21)),
        _tracker(date(2026, 1, 28)),
        _tracker(date(2026, 1, 6), TrackerStatus.SKIPPED),  # a Tuesday
        _tracker(date(2026, 1, 13), TrackerStatus.SKIPPED),
    ]

    rates = _weekday_rates(habit, trackers)

    assert rates[TUE] == 0.0  # explicitly skipped
    assert rates[THU] == 0.0  # auto-skipped by Wednesday's completion
    assert rates[WED] == 1.0


def test_weekday_rates_are_zero_without_trackers():
    rates = _weekday_rates(_habit(frequency=1, range_=1), [])

    assert rates == [0.0] * 7


def test_daily_habit_weekday_rates_are_plain_completion_share():
    """frequency == range (daily): the share is unaffected by normalization."""
    habit = _habit(frequency=1, range_=1)
    trackers = [_tracker(date(2026, 1, 5)), _tracker(date(2026, 1, 12))]

    rates = _weekday_rates(habit, trackers)

    assert rates[MON] == 0.5  # 2 of 4 Mondays
    assert rates[TUE] == 0.0
