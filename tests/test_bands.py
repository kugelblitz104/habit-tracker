"""Unit tests for the compute_band function."""

from datetime import date, timedelta

from habit_tracker.constants import TaskBand, TaskStatus, compute_band

TODAY = date(2026, 7, 8)


class TestHiddenBand:
    """Closed tasks are hidden regardless of priority or due date."""

    def test_done_is_hidden(self):
        assert compute_band(TaskStatus.DONE, 0, None, TODAY) == TaskBand.HIDDEN

    def test_cancelled_is_hidden(self):
        assert compute_band(TaskStatus.CANCELLED, 0, None, TODAY) == TaskBand.HIDDEN

    def test_done_with_due_today_is_hidden(self):
        """Hidden wins over now - first match wins."""
        assert compute_band(TaskStatus.DONE, 3, TODAY, TODAY) == TaskBand.HIDDEN

    def test_cancelled_overdue_is_hidden(self):
        overdue = TODAY - timedelta(days=5)
        assert compute_band(TaskStatus.CANCELLED, 3, overdue, TODAY) == TaskBand.HIDDEN


class TestNowBand:
    """Overdue, due today, or priority 3 tasks are 'now'."""

    def test_due_exactly_today_is_now(self):
        assert compute_band(TaskStatus.OPEN, 0, TODAY, TODAY) == TaskBand.NOW

    def test_overdue_is_now(self):
        overdue = TODAY - timedelta(days=1)
        assert compute_band(TaskStatus.OPEN, 0, overdue, TODAY) == TaskBand.NOW

    def test_far_overdue_is_now(self):
        overdue = TODAY - timedelta(days=365)
        assert compute_band(TaskStatus.OPEN, 0, overdue, TODAY) == TaskBand.NOW

    def test_priority_3_no_due_date_is_now(self):
        assert compute_band(TaskStatus.OPEN, 3, None, TODAY) == TaskBand.NOW

    def test_priority_3_due_far_future_is_now(self):
        """Priority 3 wins even if the due date alone would be 'whenever'."""
        far_future = TODAY + timedelta(days=30)
        assert compute_band(TaskStatus.OPEN, 3, far_future, TODAY) == TaskBand.NOW

    def test_blocked_status_does_not_change_band(self):
        """blocked/deferred statuses do not alter the band."""
        assert compute_band(TaskStatus.BLOCKED, 0, TODAY, TODAY) == TaskBand.NOW
        assert compute_band(TaskStatus.DEFERRED, 3, None, TODAY) == TaskBand.NOW


class TestSoonBand:
    """Due within 7 days or priority 2 tasks are 'soon'."""

    def test_due_tomorrow_is_soon(self):
        tomorrow = TODAY + timedelta(days=1)
        assert compute_band(TaskStatus.OPEN, 0, tomorrow, TODAY) == TaskBand.SOON

    def test_due_today_plus_7_is_soon(self):
        """Boundary: exactly 7 days out is still 'soon'."""
        boundary = TODAY + timedelta(days=7)
        assert compute_band(TaskStatus.OPEN, 0, boundary, TODAY) == TaskBand.SOON

    def test_priority_2_no_due_date_is_soon(self):
        assert compute_band(TaskStatus.OPEN, 2, None, TODAY) == TaskBand.SOON

    def test_priority_2_due_far_future_is_soon(self):
        far_future = TODAY + timedelta(days=30)
        assert compute_band(TaskStatus.OPEN, 2, far_future, TODAY) == TaskBand.SOON


class TestWheneverBand:
    """Everything else lands in 'whenever'."""

    def test_due_today_plus_8_is_whenever(self):
        """Boundary: 8 days out falls outside the 'soon' window."""
        beyond = TODAY + timedelta(days=8)
        assert compute_band(TaskStatus.OPEN, 0, beyond, TODAY) == TaskBand.WHENEVER

    def test_priority_0_no_due_date_is_whenever(self):
        assert compute_band(TaskStatus.OPEN, 0, None, TODAY) == TaskBand.WHENEVER

    def test_priority_1_no_due_date_is_whenever(self):
        assert compute_band(TaskStatus.OPEN, 1, None, TODAY) == TaskBand.WHENEVER

    def test_in_progress_no_signals_is_whenever(self):
        assert (
            compute_band(TaskStatus.IN_PROGRESS, 0, None, TODAY) == TaskBand.WHENEVER
        )


class TestTodayDefault:
    """today defaults to date.today() when not provided."""

    def test_due_today_defaults_to_now(self):
        assert compute_band(TaskStatus.OPEN, 0, date.today()) == TaskBand.NOW

    def test_no_due_date_defaults_to_whenever(self):
        assert compute_band(TaskStatus.OPEN, 0, None) == TaskBand.WHENEVER
