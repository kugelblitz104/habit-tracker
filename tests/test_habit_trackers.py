"""Tests for the habit tracker-listing endpoints.

GET /habits/{habit_id}/trackers and its date-paginated /lite variant. Split
out of test_habits.py, which was 4.4x the size of the router it covers.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from habit_tracker.constants import TrackerStatus
from tests.factories import HabitFactory, TrackerFactory, UserFactory


class TestListHabitTrackers:
    """Tests for GET /habits/{habit_id}/trackers endpoint."""

    async def test_list_habit_trackers_basic(self, client, db_session, login_as):
        """List trackers for a habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today())
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 2

    async def test_list_habit_trackers_pagination(self, client, db_session, login_as):
        """Verify pagination with limit parameter."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 3
        assert data["limit"] == 3

    async def test_list_habit_trackers_order(self, client, db_session, login_as):
        """Verify trackers ordered by date descending."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=2))
        TrackerFactory(habit=habit, dated=date.today())
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        trackers = response.json()["trackers"]

        # Should be ordered by date descending
        dates = [t["dated"] for t in trackers]
        assert dates == sorted(dates, reverse=True)

    async def test_list_habit_trackers_empty(self, client, db_session, login_as):
        """Return empty list for habit with no trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 0
        assert data["total"] == 0

    async def test_list_habit_trackers_unauthorized(self, client, db_session, login_as):
        """User cannot access other's habit trackers (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 403

    async def test_list_habit_trackers_default_limit(
        self, client, db_session, login_as
    ):
        """Verify default limit of 5."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert len(data["trackers"]) == 5

    async def test_list_habit_trackers_custom_limit(self, client, db_session, login_as):
        """Test with custom limit value."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers?limit=7")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 7
        assert len(data["trackers"]) == 7

    async def test_list_habit_trackers_returns_total(
        self, client, db_session, login_as
    ):
        """Verify total count in response."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(8):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 3
        assert data["total"] == 8

    async def test_list_habit_trackers_offset_skips(self, client, db_session, login_as):
        """offset skips rows without changing total."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(8):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        first = await client.get(f"/habits/{habit.id}/trackers?limit=3&offset=0")
        second = await client.get(f"/habits/{habit.id}/trackers?limit=3&offset=3")
        assert first.status_code == 200
        assert second.status_code == 200

        first_ids = [t["id"] for t in first.json()["trackers"]]
        second_ids = [t["id"] for t in second.json()["trackers"]]
        assert len(second_ids) == 3
        assert set(first_ids).isdisjoint(second_ids)
        assert first.json()["total"] == 8
        assert second.json()["total"] == 8
        assert second.json()["offset"] == 3

    async def test_list_habit_trackers_offset_past_end_is_empty(
        self, client, db_session, login_as
    ):
        """An offset beyond total returns no rows but still reports total."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today())
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers?offset=50")
        assert response.status_code == 200
        data = response.json()
        assert data["trackers"] == []
        assert data["total"] == 1


class TestListHabitTrackersLite:
    """Tests for GET /habits/{habit_id}/trackers/lite endpoint with date-based pagination."""

    async def test_list_trackers_lite_default_params(
        self, client, db_session, login_as
    ):
        """List trackers with default parameters (today as end_date, 42 days)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create trackers for last 10 days
        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert data["days"] == 42
        assert data["end_date"] == date.today().isoformat()
        assert data["has_previous"] is False

    async def test_list_trackers_lite_with_end_date(self, client, db_session, login_as):
        """List trackers with specific end_date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create trackers for specific dates
        target_date = date.today() - timedelta(days=10)
        for i in range(5):
            TrackerFactory(habit=habit, dated=target_date - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            f"/habits/{habit.id}/trackers/lite?end_date={target_date.isoformat()}&days=7"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["end_date"] == target_date.isoformat()
        assert data["days"] == 7
        # Should include trackers from target_date to target_date - 6 days
        assert data["total"] == 5

    async def test_list_trackers_lite_has_previous_true(
        self, client, db_session, login_as
    ):
        """has_previous is True when older trackers exist."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create recent trackers
        for i in range(5):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        # Create older tracker outside the range
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=50))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["has_previous"] is True
        assert data["total"] == 5  # Only recent 5 within the 7-day window

    async def test_list_trackers_lite_has_previous_false(
        self, client, db_session, login_as
    ):
        """has_previous is False when no older trackers exist."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create only recent trackers within the range
        for i in range(3):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=42")
        assert response.status_code == 200
        data = response.json()
        assert data["has_previous"] is False

    async def test_list_trackers_lite_pagination(self, client, db_session, login_as):
        """Test paginating through trackers with different end_dates."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create trackers spanning 60 days
        for i in range(60):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        # First page (most recent 30 days)
        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=30")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 30
        assert data["has_previous"] is True

        # Second page (next 30 days)
        prev_end_date = date.today() - timedelta(days=30)
        response = await client.get(
            f"/habits/{habit.id}/trackers/lite?end_date={prev_end_date.isoformat()}&days=30"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 30
        assert data["has_previous"] is False

    async def test_list_trackers_lite_empty_range(self, client, db_session, login_as):
        """Returns empty list when no trackers in date range."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create tracker outside the range
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=100))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["trackers"]) == 0
        assert data["has_previous"] is True  # There is an older tracker

    async def test_list_trackers_lite_unauthorized(self, client, db_session, login_as):
        """User cannot list other user's trackers (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 403

    async def test_list_trackers_lite_nonexistent_habit(
        self, client, db_session, login_as
    ):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/99999/trackers/lite")
        assert response.status_code == 404

    async def test_list_trackers_lite_has_note_flag(self, client, db_session, login_as):
        """Verify has_note flag is correctly set."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), note="Has a note")
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1), note="")
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=2), note=None)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 200
        data = response.json()
        trackers = data["trackers"]
        assert len(trackers) == 3
        # Ordered by date descending
        assert trackers[0]["has_note"] is True  # today - has note
        assert trackers[1]["has_note"] is False  # yesterday - empty string
        assert trackers[2]["has_note"] is False  # 2 days ago - None

    async def test_list_trackers_lite_large_days_value(
        self, client, db_session, login_as
    ):
        """A large days value (full history for an old habit) is accepted."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today())
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=1000")
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 1000

    async def test_list_trackers_lite_default_end_date_honors_tz(
        self, client, db_session, login_as
    ):
        """The default end_date is "today" in the requested zone."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        for tz_name in ("Etc/GMT+12", "Etc/GMT-14"):
            expected_today = datetime.now(ZoneInfo(tz_name)).date()
            response = await client.get(
                f"/habits/{habit.id}/trackers/lite", params={"tz": tz_name}
            )
            assert response.status_code == 200
            assert response.json()["end_date"] == expected_today.isoformat()

    async def test_list_trackers_lite_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            f"/habits/{habit.id}/trackers/lite", params={"tz": "Not/AZone"}
        )
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    async def test_auto_skipped_dates_use_history_outside_the_window(
        self, client, db_session, login_as
    ):
        """A completion BEFORE the requested range still auto-skips days in it.

        This is the whole point of returning the flag from the server: a 4-day
        window (the phone dashboard) holds no tracker rows at all here, yet all
        four days are auto-skipped by a completion 5 days back. A client
        computing this from the response's own `trackers` could never know.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=7)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=5))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=4")
        assert response.status_code == 200
        data = response.json()

        assert data["trackers"] == []  # nothing in the 4-day window
        assert data["auto_skipped_dates"] == [
            (date.today() - timedelta(days=offset)).isoformat()
            for offset in (3, 2, 1, 0)
        ]

    async def test_auto_skipped_dates_empty_for_daily_habit(
        self, client, db_session, login_as
    ):
        """frequency >= range: every day needs action, so nothing auto-skips."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=4")
        assert response.status_code == 200
        assert response.json()["auto_skipped_dates"] == []

    async def test_auto_skipped_dates_ignore_skipped_trackers(
        self, client, db_session, login_as
    ):
        """Only COMPLETED rows satisfy the goal - an explicit skip does not."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=7)
        await db_session.commit()

        TrackerFactory(
            habit=habit,
            dated=date.today() - timedelta(days=5),
            status=TrackerStatus.SKIPPED,
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=4")
        assert response.status_code == 200
        assert response.json()["auto_skipped_dates"] == []

    async def test_auto_skipped_dates_are_the_raw_date_predicate(
        self, client, db_session, login_as
    ):
        """A date can be auto-skipped AND carry a completed row.

        The endpoint reports the date-level predicate; letting an explicit row
        win is the consumer's job (matches `calculate_streaks`).
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=7)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=5))
        TrackerFactory(habit=habit, dated=date.today())
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=4")
        assert response.status_code == 200
        data = response.json()

        assert date.today().isoformat() in data["auto_skipped_dates"]
        assert [t["dated"] for t in data["trackers"]] == [date.today().isoformat()]

    async def test_list_trackers_lite_total_is_the_window_count(
        self, client, db_session, login_as
    ):
        """total counts the whole window, not the returned page."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=30&limit=4")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 4
        assert data["total"] == 10
        assert data["limit"] == 4
        assert data["offset"] == 0

    async def test_list_trackers_lite_offset_slices_the_window(
        self, client, db_session, login_as
    ):
        """limit and offset walk the window without overlap."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        first = await client.get(f"/habits/{habit.id}/trackers/lite?days=30&limit=4")
        second = await client.get(
            f"/habits/{habit.id}/trackers/lite?days=30&limit=4&offset=4"
        )
        first_ids = [t["id"] for t in first.json()["trackers"]]
        second_ids = [t["id"] for t in second.json()["trackers"]]
        assert len(second_ids) == 4
        assert set(first_ids).isdisjoint(second_ids)
        assert second.json()["offset"] == 4

    async def test_list_trackers_lite_range_fields_are_page_independent(
        self, client, db_session, login_as
    ):
        """end_date, days, has_previous and auto_skipped_dates describe the
        window, so every page of a walk reports them identically.

        The client keeps only the first page's copy, so a page-dependent value
        here would corrupt streak rendering with no visible error.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=7)
        await db_session.commit()

        for i in range(12):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        await login_as(user)

        pages = []
        for offset in (0, 4, 8):
            response = await client.get(
                f"/habits/{habit.id}/trackers/lite?days=30&limit=4&offset={offset}"
            )
            assert response.status_code == 200
            pages.append(response.json())

        range_fields = [
            {
                k: p[k]
                for k in ("end_date", "days", "has_previous", "auto_skipped_dates")
            }
            for p in pages
        ]
        assert range_fields[0] == range_fields[1] == range_fields[2]
