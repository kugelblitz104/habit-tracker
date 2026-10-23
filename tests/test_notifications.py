"""Unit tests for the pure scheduling rules in ``services.notifications``.

Everything here builds ORM instances in memory - no session, no API - so each
rule can be pinned to an exact instant. Times are naive UTC, the server's wire
contract. The profile zone is America/New_York, where 2026's DST starts on
Sunday 8 March and ends on Sunday 1 November.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from habit_tracker.constants import TaskStatus
from habit_tracker.schemas.db_models import Countdown, Habit, Profile, Task
from habit_tracker.services.notifications import (
    next_countdown_fire,
    next_fire,
    next_habit_fire,
    next_journal_fire,
    next_occurrence,
    next_task_fire,
    offset_label,
    task_body,
    task_fire_times,
    to_utc,
)

NY = "America/New_York"


def _profile(**overrides) -> Profile:
    fields = {
        "id": 1,
        "timezone": NY,
        "notify_task_due": True,
        "notify_task_scheduled": True,
        "notify_habits": True,
        "notify_countdowns": True,
        "notify_journal": True,
        "task_due_reminder_offsets": [60, 15],
        "task_scheduled_reminder_offsets": [],
        "task_reminder_default_time": time(9, 0),
        "journal_enabled": True,
        "journal_prompt_time": time(21, 0),
    }
    fields.update(overrides)
    return Profile(**fields)


def _task(**overrides) -> Task:
    fields = {
        "id": 7,
        "profile_id": 1,
        "title": "Pay rent",
        "status": TaskStatus.OPEN,
        "due_date": None,
        "due_time": None,
        "scheduled_date": None,
        "scheduled_time": None,
        "due_reminder_offsets": None,
        "scheduled_reminder_offsets": None,
    }
    fields.update(overrides)
    return Task(**fields)


class TestToUtc:
    def test_winter_offset_is_five_hours(self):
        assert to_utc(date(2026, 1, 15), time(9, 0), ZoneInfo(NY)) == datetime(
            2026, 1, 15, 14, 0
        )

    def test_summer_offset_is_four_hours(self):
        assert to_utc(date(2026, 7, 15), time(9, 0), ZoneInfo(NY)) == datetime(
            2026, 7, 15, 13, 0
        )


class TestTaskFireTimes:
    def test_offsets_count_back_from_the_due_time(self):
        task = _task(due_date=date(2026, 1, 16), due_time=time(17, 0))

        assert sorted(task_fire_times(task, _profile())) == [
            datetime(2026, 1, 16, 21, 0),  # 16:00 local, 60 min before
            datetime(2026, 1, 16, 21, 45),  # 16:45 local, 15 min before
        ]

    def test_date_only_task_uses_the_profile_default_time(self):
        task = _task(due_date=date(2026, 1, 16))

        times = task_fire_times(task, _profile(task_due_reminder_offsets=[0]))

        assert list(times) == [datetime(2026, 1, 16, 14, 0)]  # 09:00 local

    def test_a_day_offset_keeps_wall_time_across_spring_forward(self):
        # Due Monday 9 March 09:00 EDT; "1 day before" is Sunday 8 March 09:00,
        # which is still 09:00 local although the offset changed overnight.
        task = _task(due_date=date(2026, 3, 9), due_time=time(9, 0))

        times = task_fire_times(task, _profile(task_due_reminder_offsets=[1440]))

        assert list(times) == [datetime(2026, 3, 8, 13, 0)]

    def test_a_week_offset_keeps_wall_time_across_fall_back(self):
        # Due Friday 6 November 09:00 EST; one week earlier is Friday
        # 30 October 09:00 EDT.
        task = _task(due_date=date(2026, 11, 6), due_time=time(9, 0))

        times = task_fire_times(task, _profile(task_due_reminder_offsets=[10080]))

        assert list(times) == [datetime(2026, 10, 30, 13, 0)]

    def test_due_and_scheduled_sharing_an_instant_appear_once(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            due_date=date(2026, 1, 16),
            due_time=time(9, 0),
            scheduled_date=date(2026, 1, 16),
            scheduled_time=time(9, 0),
        )
        profile = _profile(
            task_due_reminder_offsets=[15], task_scheduled_reminder_offsets=[15]
        )

        times = task_fire_times(task, profile)

        assert times == {
            datetime(2026, 1, 16, 13, 45): [("due", 15), ("scheduled", 15)]
        }

    def test_clearing_one_of_two_coincident_dates_keeps_the_shared_instant(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            due_date=None,
            scheduled_date=date(2026, 1, 16),
            scheduled_time=time(9, 0),
        )
        profile = _profile(
            task_due_reminder_offsets=[15], task_scheduled_reminder_offsets=[15]
        )

        assert list(task_fire_times(task, profile)) == [datetime(2026, 1, 16, 13, 45)]

    def test_one_toggle_off_leaves_the_other_dates_times(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            due_date=date(2026, 1, 16),
            due_time=time(9, 0),
            scheduled_date=date(2026, 1, 15),
            scheduled_time=time(9, 0),
        )
        profile = _profile(
            notify_task_due=False,
            task_due_reminder_offsets=[0],
            task_scheduled_reminder_offsets=[0],
        )

        assert list(task_fire_times(task, profile)) == [datetime(2026, 1, 15, 14, 0)]

    def test_a_tasks_own_offsets_replace_the_default(self):
        task = _task(
            due_date=date(2026, 1, 16), due_time=time(9, 0), due_reminder_offsets=[5]
        )

        assert list(task_fire_times(task, _profile())) == [
            datetime(2026, 1, 16, 13, 55)
        ]

    def test_an_empty_task_list_silences_that_date(self):
        task = _task(
            due_date=date(2026, 1, 16), due_time=time(9, 0), due_reminder_offsets=[]
        )

        assert task_fire_times(task, _profile()) == {}

    def test_the_profile_toggle_silences_custom_offsets_too(self):
        task = _task(
            due_date=date(2026, 1, 16), due_time=time(9, 0), due_reminder_offsets=[5]
        )

        assert task_fire_times(task, _profile(notify_task_due=False)) == {}

    @pytest.mark.parametrize("closed", [TaskStatus.DONE, TaskStatus.CANCELLED])
    def test_a_closed_task_has_none(self, closed):
        task = _task(status=closed, due_date=date(2026, 1, 16))

        assert task_fire_times(task, _profile()) == {}

    def test_no_profile_zone_means_nothing_fires(self):
        task = _task(due_date=date(2026, 1, 16))

        assert task_fire_times(task, _profile(timezone=None)) == {}


class TestNextTaskFire:
    def test_returns_the_earliest_time_after_now(self):
        task = _task(due_date=date(2026, 1, 16), due_time=time(9, 0))

        fire = next_task_fire(task, _profile(), datetime(2026, 1, 16, 0, 0))

        assert fire == datetime(2026, 1, 16, 13, 0)

    def test_skips_offsets_already_past(self):
        # Created at 08:30 local for 09:00: only the 15-minute reminder is left.
        task = _task(due_date=date(2026, 1, 16), due_time=time(9, 0))

        fire = next_task_fire(task, _profile(), datetime(2026, 1, 16, 13, 30))

        assert fire == datetime(2026, 1, 16, 13, 45)

    def test_offsets_missed_during_downtime_collapse(self):
        # Down from 07:55 to 08:50 local: both reminders are behind `now`, so
        # nothing is left rather than a burst of stale sends.
        task = _task(due_date=date(2026, 1, 16), due_time=time(9, 0))

        assert next_task_fire(task, _profile(), datetime(2026, 1, 16, 13, 50)) is None


class TestTaskBody:
    def test_due_only(self):
        task = _task(due_date=date(2026, 1, 16), due_time=time(9, 0))

        body = task_body(task, _profile(), datetime(2026, 1, 16, 13, 45))

        assert body == "Due in 15 min"

    def test_scheduled_only(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            scheduled_date=date(2026, 1, 16),
            scheduled_time=time(9, 0),
        )
        profile = _profile(task_scheduled_reminder_offsets=[60])

        body = task_body(task, profile, datetime(2026, 1, 16, 13, 0))

        assert body == "Scheduled in 1 hour"

    def test_both_with_the_same_offset(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            due_date=date(2026, 1, 16),
            due_time=time(9, 0),
            scheduled_date=date(2026, 1, 16),
            scheduled_time=time(9, 0),
        )
        profile = _profile(
            task_due_reminder_offsets=[15], task_scheduled_reminder_offsets=[15]
        )

        body = task_body(task, profile, datetime(2026, 1, 16, 13, 45))

        assert body == "Due and scheduled in 15 min"

    def test_both_with_different_offsets(self):
        task = _task(
            status=TaskStatus.SCHEDULED,
            due_date=date(2026, 1, 17),
            due_time=time(9, 0),
            scheduled_date=date(2026, 1, 16),
            scheduled_time=time(9, 0),
        )
        profile = _profile(
            task_due_reminder_offsets=[1440], task_scheduled_reminder_offsets=[0]
        )

        body = task_body(task, profile, datetime(2026, 1, 16, 14, 0))

        assert body == "Due in 1 day, scheduled now"


@pytest.mark.parametrize(
    ("minutes", "label"),
    [
        (0, "now"),
        (1, "1 min"),
        (90, "90 min"),
        (60, "1 hour"),
        (120, "2 hours"),
        (1440, "1 day"),
        (2880, "2 days"),
        (10080, "1 week"),
        (20160, "2 weeks"),
    ],
)
def test_offset_label(minutes, label):
    assert offset_label(minutes) == label


def _habit(**overrides) -> Habit:
    fields = {
        "id": 3,
        "profile_id": 1,
        "name": "Stretch",
        "question": "Did you stretch?",
        "reminder": True,
        "reminder_time": time(7, 30),
        "reminder_days": 0b0011111,  # Monday to Friday
        "archived": False,
    }
    fields.update(overrides)
    return Habit(**fields)


class TestNextHabitFire:
    def test_fires_later_today(self):
        # Thursday 15 January, 06:00 local.
        fire = next_habit_fire(_habit(), _profile(), datetime(2026, 1, 15, 11, 0))

        assert fire == datetime(2026, 1, 15, 12, 30)

    def test_skips_to_the_next_masked_day(self):
        # Friday 16 January 08:00 local: today's time has passed and the
        # weekend is off, so the next one is Monday.
        fire = next_habit_fire(_habit(), _profile(), datetime(2026, 1, 16, 13, 0))

        assert fire == datetime(2026, 1, 19, 12, 30)

    @pytest.mark.parametrize(
        "overrides",
        [{"reminder": False}, {"reminder_time": None}, {"archived": True}],
    )
    def test_off_states(self, overrides):
        habit = _habit(**overrides)

        assert next_habit_fire(habit, _profile(), datetime(2026, 1, 15)) is None

    def test_profile_toggle_off(self):
        profile = _profile(notify_habits=False)

        assert next_habit_fire(_habit(), profile, datetime(2026, 1, 15)) is None


def _countdown(**overrides) -> Countdown:
    fields = {
        "id": 5,
        "profile_id": 1,
        "title": "Trip",
        "target_date": date(2026, 1, 20),
        "target_time": None,
        "repeat": "none",
        "archived_date": None,
    }
    fields.update(overrides)
    return Countdown(**fields)


class TestNextCountdownFire:
    def test_date_only_fires_at_the_default_time(self):
        fire = next_countdown_fire(_countdown(), _profile(), datetime(2026, 1, 15))

        assert fire == datetime(2026, 1, 20, 14, 0)

    def test_timed_fires_at_its_own_time(self):
        countdown = _countdown(target_time=time(18, 30))

        fire = next_countdown_fire(countdown, _profile(), datetime(2026, 1, 15))

        assert fire == datetime(2026, 1, 20, 23, 30)

    def test_a_past_one_time_countdown_has_none(self):
        now = datetime(2026, 1, 21)

        assert next_countdown_fire(_countdown(), _profile(), now) is None

    def test_a_repeat_rolls_forward_once_todays_time_has_passed(self):
        # Weekly from Tuesday 20 January; it is Tuesday 27 January 10:00 local.
        countdown = _countdown(repeat="weekly")

        fire = next_countdown_fire(countdown, _profile(), datetime(2026, 1, 27, 15, 0))

        assert fire == datetime(2026, 2, 3, 14, 0)

    def test_archived_has_none(self):
        countdown = _countdown(archived_date=datetime(2026, 1, 1))

        assert next_countdown_fire(countdown, _profile(), datetime(2026, 1, 15)) is None


class TestNextJournalFire:
    def test_today_then_tomorrow(self):
        profile = _profile()

        assert next_journal_fire(profile, datetime(2026, 1, 15, 12, 0)) == datetime(
            2026, 1, 16, 2, 0
        )
        assert next_journal_fire(profile, datetime(2026, 1, 16, 2, 0)) == datetime(
            2026, 1, 17, 2, 0
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"notify_journal": False},
            {"journal_enabled": False},
            {"journal_prompt_time": None},
        ],
    )
    def test_off_states(self, overrides):
        profile = _profile(**overrides)

        assert next_journal_fire(profile, datetime(2026, 1, 15)) is None


class TestNextOccurrenceSmoke:
    """Spot checks; the full table is the parity fixture in
    test_countdown_occurrence.py."""

    def test_non_recurring_returns_the_anchor(self):
        assert next_occurrence(date(2026, 1, 1), "none", date(2026, 6, 1)) == date(
            2026, 1, 1
        )

    def test_monthly_clamps_day_31_into_february(self):
        assert next_occurrence(date(2026, 1, 31), "monthly", date(2026, 2, 1)) == (
            date(2026, 2, 28)
        )


class TestUnreadableZone:
    """A restored backup can carry a zone this server cannot construct; the
    profile then behaves as if no zone were reported."""

    @pytest.mark.parametrize("zone", ["Not/AZone", "", "../etc/passwd"])
    def test_nothing_fires(self, zone):
        profile = _profile(timezone=zone)
        task = _task(due_date=date(2026, 6, 1))
        now = datetime(2026, 1, 15)

        assert task_fire_times(task, profile) == {}
        assert next_journal_fire(profile, now) is None


class TestNextFireOverflow:
    """Dates at the edge of the calendar have no next fire time and must not raise."""

    def test_yearly_countdown_whose_next_occurrence_is_year_10000(self):
        countdown = Countdown(
            target_date=date(9999, 1, 1), target_time=None, repeat="yearly"
        )
        countdown.archived_date = None

        assert (
            next_fire("countdown", countdown, _profile(), datetime(9999, 6, 1)) is None
        )

    def test_task_whose_reminder_overflows_when_converted_to_utc(self):
        task = _task(due_date=date.max, due_time=time(23, 0), due_reminder_offsets=[0])

        assert next_fire("task", task, _profile(), datetime(2026, 1, 1)) is None
