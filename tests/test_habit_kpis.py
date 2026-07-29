"""Tests for the habit KPI/streak endpoints.

GET /habits/{habit_id}/kpis and /streaks. Split out of test_habits.py, which
was 4.4x the size of the router it covers.

Per CLAUDE.md, the KPI/streak arithmetic itself belongs in
tests/test_habit_stats.py (pure Habit/Tracker math, no session, no API) -
that file's parity harness already pins every field these endpoints surface
(total_completions, current_streak, longest_streak, thirty_day_completion_rate,
last_completed_date, weekday_completion_rates, ...) far more precisely than a
handful of HTTP round trips can. What's left here is what genuinely needs
HTTP: auth, 403/404, the ``tz`` query param, and response shape.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from habit_tracker.constants import TrackerStatus
from tests.factories import HabitFactory, TrackerFactory, UserFactory


class TestGetHabitKPIs:
    """Tests for GET /habits/{habit_id}/kpis endpoint."""

    async def test_get_habit_kpis_response_shape(self, client, db_session, login_as):
        """A new habit's KPI response carries every documented field.

        Zero trackers is the trivial case for each field (0 counts, None
        dates, all-zero rates) - the point here is that the field names the
        frontend depends on are present and correctly typed, not the
        arithmetic itself (see test_habit_stats.py for that).
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_completions"] == 0
        assert data["current_streak"] == 0
        assert data["longest_streak"] == 0
        assert data["longest_streak_end_date"] is None
        assert data["thirty_day_completion_rate"] == 0.0
        assert data["overall_completion_rate"] == 0.0
        assert data["last_completed_date"] is None
        assert data["weekday_completion_rates"] == [0.0] * 7

    async def test_get_habit_kpis_unauthorized(self, client, db_session, login_as):
        """User cannot access other's habit KPIs (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 403

    async def test_get_habit_kpis_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            f"/habits/{habit.id}/kpis", params={"tz": "Not/AZone"}
        )
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    async def test_get_habit_kpis_tz_shifts_today(self, client, db_session, login_as):
        """current_streak is computed against "today" in the requested zone.

        Etc/GMT+12 (UTC-12) and Etc/GMT-14 (UTC+14) are 26 hours apart, so
        their calendar dates always differ. A daily habit completed on
        "today" in one zone therefore has a current streak in that zone and
        none in the other - deterministic regardless of when the test runs.
        """
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        for tz_name, other_tz_name in [
            ("Etc/GMT+12", "Etc/GMT-14"),
            ("Etc/GMT-14", "Etc/GMT+12"),
        ]:
            habit = HabitFactory(user=user, frequency=1, range=1)
            await db_session.commit()

            expected_today = datetime.now(ZoneInfo(tz_name)).date()
            TrackerFactory(
                habit=habit, dated=expected_today, status=TrackerStatus.COMPLETED
            )
            await db_session.commit()

            response = await client.get(
                f"/habits/{habit.id}/kpis", params={"tz": tz_name}
            )
            assert response.status_code == 200
            assert response.json()["current_streak"] == 1

            response = await client.get(
                f"/habits/{habit.id}/kpis", params={"tz": other_tz_name}
            )
            assert response.status_code == 200
            assert response.json()["current_streak"] == 0


class TestGetHabitStreaks:
    """Tests for GET /habits/{habit_id}/streaks endpoint."""

    async def test_get_habit_streaks_empty(self, client, db_session, login_as):
        """Empty list for habit with no completions."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    async def test_get_habit_streaks_single_streak(self, client, db_session, login_as):
        """Single continuous streak."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        for i in range(5):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
                status=TrackerStatus.COMPLETED,
            )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    async def test_get_habit_streaks_with_skips(self, client, db_session, login_as):
        """Streaks including skipped days."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.COMPLETED)
        TrackerFactory(
            habit=habit,
            dated=date.today() - timedelta(days=1),
            status=TrackerStatus.SKIPPED,
        )
        TrackerFactory(
            habit=habit,
            dated=date.today() - timedelta(days=2),
            status=TrackerStatus.COMPLETED,
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200

    async def test_get_habit_streaks_unauthorized(self, client, db_session, login_as):
        """User cannot access other's habit streaks (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 403

    async def test_get_habit_streaks_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            f"/habits/{habit.id}/streaks", params={"tz": "Not/AZone"}
        )
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    async def test_get_habit_streaks_honors_tz(self, client, db_session, login_as):
        """Streaks run through "today" in the requested zone.

        A daily habit with a single tracker dated "today" in the requested
        zone yields exactly one streak ending on that date - deterministic
        regardless of when the test runs.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        tz_name = "Etc/GMT-14"
        expected_today = datetime.now(ZoneInfo(tz_name)).date()
        TrackerFactory(
            habit=habit, dated=expected_today, status=TrackerStatus.COMPLETED
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            f"/habits/{habit.id}/streaks", params={"tz": tz_name}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["end_date"] == expected_today.isoformat()
        assert data[0]["length"] == 1
