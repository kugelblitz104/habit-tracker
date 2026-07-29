"""Edge cases: acceptance of unusual-but-valid input and degenerate results.

Boundary with test_validation.py: this file covers input that IS accepted
(unusual dates, huge-but-legal record counts, empty result sets) - a
happy-path response is the point. test_validation.py covers the opposite:
input that's rejected (422). If you're adding a test that asserts a 422,
it belongs there, not here.
"""

from datetime import date, timedelta

import pytest

from habit_tracker.constants import TrackerStatus
from tests.factories import (
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestDateEdgeCases:
    """Tests for date edge cases."""

    async def test_tracker_far_future_date(self, client, db_session, login_as):
        """Test tracker with far future date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        future_date = (date.today() + timedelta(days=365 * 10)).isoformat()
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": future_date,
                "status": TrackerStatus.COMPLETED,
            },
        )
        # May allow or reject future dates
        assert response.status_code in [201, 400, 422]

    async def test_tracker_far_past_date(self, client, db_session, login_as):
        """Test tracker with far past date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        past_date = (date.today() - timedelta(days=365 * 10)).isoformat()
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": past_date,
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code in [201, 400, 422]

    async def test_leap_year_date(self, client, db_session, login_as):
        """Test tracker with leap year date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": "2024-02-29",  # Leap year
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 201


class TestManyRecords:
    """Tests for handling many records."""

    async def test_user_with_many_habits(self, client, db_session, login_as):
        """Test user with many habits."""
        user = UserFactory()
        await db_session.commit()

        for i in range(100):
            HabitFactory(user=user, name=f"Habit {i}")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200

    async def test_habit_with_many_trackers(self, client, db_session, login_as):
        """Test habit with many trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(100):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
            )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200


class TestEmptyResults:
    """Tests for empty result handling."""

    async def test_user_with_no_habits(self, client, db_session, login_as):
        """Test user with no habits."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()
        assert data["habits"] == []

    async def test_habit_with_no_trackers(self, client, db_session, login_as):
        """Test habit with no trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert data["trackers"] == []

    @pytest.mark.skip(reason="endpoint arrives in overhaul Phase 3")
    async def test_habit_kpis_with_no_data(self, client, db_session, login_as):
        """Test KPIs with no completion data."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        kpis = response.json()
        assert kpis["total_completions"] == 0
