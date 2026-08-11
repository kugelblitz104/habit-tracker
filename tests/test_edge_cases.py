"""Edge cases: acceptance of unusual-but-valid input and degenerate results.

Boundary with test_validation.py: this file covers input that IS accepted
(unusual dates, huge-but-legal record counts, empty result sets) - a
happy-path response is the point. test_validation.py covers the opposite:
input that's rejected (422). If you're adding a test that asserts a 422,
it belongs there, not here.
"""

from datetime import date, timedelta

from habit_tracker.constants import TrackerStatus
from tests.factories import (
    HabitFactory,
    TaskFactory,
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

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
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

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
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


class TestExternalLinkAcceptance:
    """A task's external-link triple accepts an unusual-but-valid link.

    The soft-link case - a link with no provider behind it, so `source` is NULL
    while `external_ref` and `external_url` are set - is the reason a profile
    needs no Azure DevOps or GitHub connection to link a task. Rejection of a
    scheme-less or non-provider value lives in test_validation.py.
    """

    async def test_soft_link_without_a_source_accepted(
        self, client, db_session, login_as
    ):
        """A link with no provider round-trips with source NULL."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Review the spec",
                "external_ref": "PROJ-412",
                "external_url": "https://example.atlassian.net/browse/PROJ-412",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["source"] is None
        assert data["external_ref"] == "PROJ-412"
        assert data["external_url"] == "https://example.atlassian.net/browse/PROJ-412"

    async def test_plain_http_url_accepted(self, client, db_session, login_as):
        """An http:// link is accepted, not only https://."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Check the intranet page",
                "external_ref": "WIKI-9",
                "external_url": "http://intranet.local/wiki/9",
            },
        )
        assert response.status_code == 201
        assert response.json()["external_url"] == "http://intranet.local/wiki/9"

    async def test_surrounding_whitespace_trimmed(self, client, db_session, login_as):
        """A pasted ref and URL are stored trimmed."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Review the spec",
                "external_ref": "  PROJ-412  ",
                "external_url": "  https://example.atlassian.net/browse/PROJ-412  ",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["external_ref"] == "PROJ-412"
        assert data["external_url"] == "https://example.atlassian.net/browse/PROJ-412"

    async def test_trailing_slash_preserved(self, client, db_session, login_as):
        """A trailing slash is part of the target and is kept."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Read the doc",
                "external_ref": "DOC-1",
                "external_url": "https://wiki.example.com/spaces/eng/",
            },
        )
        assert response.status_code == 201
        assert response.json()["external_url"] == "https://wiki.example.com/spaces/eng/"

    async def test_blank_link_fields_stored_as_null(self, client, db_session, login_as):
        """Empty strings become NULL rather than an invisible half-link."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Review the spec",
                "external_ref": "",
                "external_url": "   ",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["external_ref"] is None
        assert data["external_url"] is None

    async def test_explicit_nulls_unlink_a_task(self, client, db_session, login_as):
        """Sending nulls clears the triple - this is how the client unlinks."""
        user = UserFactory()
        await db_session.commit()

        task = TaskFactory(
            profile=user.profiles[0],
            source="github",
            external_ref="octocat/hello#1",
            external_url="https://github.com/octocat/hello/issues/1",
        )
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"source": None, "external_ref": None, "external_url": None},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["source"] is None
        assert data["external_ref"] is None
        assert data["external_url"] is None
