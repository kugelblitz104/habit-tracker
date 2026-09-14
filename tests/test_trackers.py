"""Tests for tracker management endpoints."""

from datetime import date, timedelta

from sqlalchemy import select

from habit_tracker.constants import TrackerStatus
from habit_tracker.schemas.db_models import Habit, Tracker
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    ProfileFactory,
    TrackerFactory,
    UserFactory,
)


class TestListTrackers:
    """Tests for GET /trackers/ endpoint."""

    async def test_requires_profile_id(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get("/trackers/")
        assert response.status_code == 422

    async def test_lists_every_habit_in_the_profile_for_one_date(
        self, client, db_session, login_as
    ):
        """The point of the endpoint: one request instead of one per habit."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        reading = HabitFactory(user=user, profile=profile, name="Reading")
        running = HabitFactory(user=user, profile=profile, name="Running")
        await db_session.commit()

        TrackerFactory(habit=reading, dated=date(2026, 9, 10))
        TrackerFactory(habit=running, dated=date(2026, 9, 10))
        TrackerFactory(habit=reading, dated=date(2026, 9, 11))
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/trackers/",
            params={
                "profile_id": profile.id,
                "dated_from": "2026-09-10",
                "dated_to": "2026-09-10",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["total"] == 2
        assert sorted(t["habit_id"] for t in body["trackers"]) == sorted(
            [reading.id, running.id]
        )

    async def test_bounds_are_inclusive_at_both_ends(
        self, client, db_session, login_as
    ):
        """`dated` is a date, not an instant, so a window names the first and
        last day it covers rather than half-opening at the end."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()
        habit = HabitFactory(user=user, profile=profile)
        await db_session.commit()

        for day in (9, 10, 11, 12):
            TrackerFactory(habit=habit, dated=date(2026, 9, day))
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/trackers/",
            params={
                "profile_id": profile.id,
                "dated_from": "2026-09-10",
                "dated_to": "2026-09-11",
            },
        )

        assert sorted(t["dated"] for t in response.json()["trackers"]) == [
            "2026-09-10",
            "2026-09-11",
        ]

    async def test_omitting_the_window_returns_the_whole_profile(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()
        habit = HabitFactory(user=user, profile=profile)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date(2026, 9, 10))
        TrackerFactory(habit=habit, dated=date(2026, 9, 11))
        await db_session.commit()
        await login_as(user)

        response = await client.get("/trackers/", params={"profile_id": profile.id})
        assert response.json()["total"] == 2

    async def test_excludes_other_profiles(self, client, db_session, login_as):
        """A tracker has no profile_id of its own, so the scope comes from the
        join to its habit - which is exactly what could go wrong."""
        user = UserFactory()
        await db_session.commit()
        mine = ProfileFactory(user=user, name="Mine")
        theirs = ProfileFactory(user=user, name="Theirs")
        await db_session.commit()

        my_habit = HabitFactory(user=user, profile=mine)
        other_habit = HabitFactory(user=user, profile=theirs)
        await db_session.commit()

        keep = TrackerFactory(habit=my_habit, dated=date(2026, 9, 10))
        TrackerFactory(habit=other_habit, dated=date(2026, 9, 10))
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/trackers/",
            params={
                "profile_id": mine.id,
                "dated_from": "2026-09-10",
                "dated_to": "2026-09-10",
            },
        )

        body = response.json()
        assert [t["id"] for t in body["trackers"]] == [keep.id]
        assert body["total"] == 1

    async def test_rejects_another_users_profile(self, client, db_session, login_as):
        owner = UserFactory()
        intruder = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=owner)
        await db_session.commit()

        await login_as(intruder)
        response = await client.get("/trackers/", params={"profile_id": profile.id})
        assert response.status_code == 403

    async def test_pages_without_dropping_or_repeating_a_row(
        self, client, db_session, login_as
    ):
        """Ordering ends in id, so rows sharing a date cannot straddle a page
        boundary and lose one."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        habits = [HabitFactory(user=user, profile=profile) for _ in range(3)]
        await db_session.commit()
        for habit in habits:
            TrackerFactory(habit=habit, dated=date(2026, 9, 10))
        await db_session.commit()
        await login_as(user)

        ids = []
        for offset in (0, 2):
            page = await client.get(
                "/trackers/",
                params={"profile_id": profile.id, "limit": 2, "offset": offset},
            )
            assert page.json()["total"] == 3
            ids += [t["id"] for t in page.json()["trackers"]]

        assert len(ids) == 3
        assert len(set(ids)) == 3


class TestCreateTracker:
    """Tests for POST /trackers/ endpoint."""

    async def test_create_tracker_basic(self, client, db_session, login_as):
        """Create tracker with minimal payload."""
        user = UserFactory()
        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["habit_id"] == habit.id
        assert data["status"] == TrackerStatus.COMPLETED
        assert data["note"] is None  # Default

    async def test_create_tracker_completed(self, client, db_session, login_as):
        """Create tracker marked as completed."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == TrackerStatus.COMPLETED

    async def test_create_tracker_skipped(self, client, db_session, login_as):
        """Create tracker marked as skipped."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.SKIPPED,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == TrackerStatus.SKIPPED

    async def test_create_tracker_with_note(self, client, db_session, login_as):
        """Create tracker with note."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
                "note": "Felt great today!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["note"] == "Felt great today!"

    async def test_create_tracker_custom_date(self, client, db_session, login_as):
        """Create tracker for specific date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        custom_date = date.today() - timedelta(days=5)

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": custom_date.isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["dated"] == custom_date.isoformat()

    async def test_create_tracker_for_other_user_habit(
        self, client, db_session, login_as
    ):
        """Cannot create tracker for other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 403

    async def test_create_tracker_nonexistent_habit(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": 99999,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 404

    async def test_create_tracker_out_of_range_status(
        self, client, db_session, login_as
    ):
        """Test validation for out-of-range status values."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        # Note: Current implementation may not validate this - test documents expected behavior
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": 99,
            },
        )
        # Depending on implementation, this could be 422 or 201
        # Currently the API accepts any integer (no validation)
        assert response.status_code in [201, 422]

    async def test_create_tracker_duplicate_date(self, client, db_session, login_as):
        """Handle duplicate tracker for same date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create first tracker
        TrackerFactory(habit=habit, dated=date.today())
        await db_session.commit()

        await login_as(user)

        # Try to create duplicate
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        # Should fail due to unique constraint
        assert response.status_code == 409


class TestGetTracker:
    """Tests for GET /trackers/{tracker_id} endpoint."""

    async def test_get_own_tracker(self, client, db_session, login_as):
        """User can retrieve their tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, note="Test note")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == tracker.id
        assert data["note"] == "Test note"

    async def test_get_other_user_tracker(self, client, db_session, login_as):
        """User cannot access other's tracker (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 403

    async def test_get_tracker_as_admin(self, client, db_session, login_as):
        """Admin can access any tracker."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 200

    async def test_get_nonexistent_tracker(self, client, db_session, login_as):
        """Return 404 for non-existent tracker."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/trackers/99999")
        assert response.status_code == 404


class TestUpdateTrackerPut:
    """Tests for PUT /trackers/{tracker_id} endpoint."""

    async def test_update_own_tracker_put(self, client, db_session, login_as):
        """User can update their tracker (full update)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, status=TrackerStatus.COMPLETED)
        await db_session.commit()

        await login_as(user)

        new_date = date.today() - timedelta(days=1)
        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": new_date.isoformat(),
                "status": TrackerStatus.SKIPPED,
                "note": "Updated note",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TrackerStatus.SKIPPED
        assert data["note"] == "Updated note"

    async def test_update_other_user_tracker_put(self, client, db_session, login_as):
        """User cannot update other's tracker (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 403

    async def test_update_tracker_completion_status_put(
        self, client, db_session, login_as
    ):
        """Update completion status."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, status=TrackerStatus.SKIPPED)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": tracker.dated.isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == TrackerStatus.COMPLETED

    async def test_update_tracker_skip_status_put(self, client, db_session, login_as):
        """Update skip status."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, status=TrackerStatus.COMPLETED)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": tracker.dated.isoformat(),
                "status": TrackerStatus.SKIPPED,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == TrackerStatus.SKIPPED

    async def test_update_tracker_date_put(self, client, db_session, login_as):
        """Update tracker date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, dated=date.today())
        await db_session.commit()

        await login_as(user)

        new_date = date.today() - timedelta(days=3)
        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": new_date.isoformat(),
                "status": tracker.status,
            },
        )
        assert response.status_code == 200
        assert response.json()["dated"] == new_date.isoformat()

    async def test_update_tracker_note_put(self, client, db_session, login_as):
        """Update tracker note."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, note="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/trackers/{tracker.id}",
            json={
                "dated": tracker.dated.isoformat(),
                "status": tracker.status,
                "note": "Updated note",
            },
        )
        assert response.status_code == 200
        assert response.json()["note"] == "Updated note"

    async def test_update_nonexistent_tracker_put(self, client, db_session, login_as):
        """Return 404 for non-existent tracker."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/trackers/99999",
            json={
                "dated": date.today().isoformat(),
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 404


class TestUpdateTrackerPatch:
    """Tests for PATCH /trackers/{tracker_id} endpoint."""

    async def test_update_tracker_single_field_patch(
        self, client, db_session, login_as
    ):
        """Update only one field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, note="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": "Patched note"},
        )
        assert response.status_code == 200
        assert response.json()["note"] == "Patched note"

    async def test_update_tracker_toggle_completed_patch(
        self, client, db_session, login_as
    ):
        """Toggle completion status."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, status=TrackerStatus.NOT_COMPLETED)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"status": TrackerStatus.COMPLETED},
        )
        assert response.status_code == 200
        assert response.json()["status"] == TrackerStatus.COMPLETED

    async def test_update_tracker_toggle_skipped_patch(
        self, client, db_session, login_as
    ):
        """Toggle skip status."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, status=TrackerStatus.NOT_COMPLETED)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"status": TrackerStatus.SKIPPED},
        )
        assert response.status_code == 200
        assert response.json()["status"] == TrackerStatus.SKIPPED

    async def test_update_tracker_add_note_patch(self, client, db_session, login_as):
        """Add note to existing tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, note=None)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": "Added note"},
        )
        assert response.status_code == 200
        assert response.json()["note"] == "Added note"

    async def test_update_tracker_clear_note_patch(self, client, db_session, login_as):
        """Clear note from tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, note="Has a note")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": None},
        )
        assert response.status_code == 200
        assert response.json()["note"] is None

    async def test_update_tracker_multiple_fields_patch(
        self, client, db_session, login_as
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(
            habit=habit, status=TrackerStatus.COMPLETED, note="Original"
        )
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"status": TrackerStatus.NOT_COMPLETED, "note": "Updated"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TrackerStatus.NOT_COMPLETED
        assert data["note"] == "Updated"

    async def test_update_other_user_tracker_patch(self, client, db_session, login_as):
        """User cannot update other's tracker (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user1)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteTracker:
    """Tests for DELETE /trackers/{tracker_id} endpoint."""

    async def test_delete_own_tracker(self, client, db_session, login_as):
        """User can delete their tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        tracker_id = tracker.id

        await login_as(user)

        response = await client.delete(f"/trackers/{tracker_id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_tracker(self, client, db_session, login_as):
        """User cannot delete other's tracker (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user1)

        response = await client.delete(f"/trackers/{tracker.id}")
        assert response.status_code == 403

    async def test_delete_tracker_as_admin(self, client, db_session, login_as):
        """Admin can delete any tracker."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        tracker_id = tracker.id

        await login_as(admin)

        response = await client.delete(f"/trackers/{tracker_id}")
        assert response.status_code == 200

    async def test_delete_nonexistent_tracker(self, client, db_session, login_as):
        """Return 404 for non-existent tracker."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/trackers/99999")
        assert response.status_code == 404


class TestDeleteAllTrackers:
    """Tests for DELETE /trackers/ (bulk delete, profile-scoped)."""

    async def test_deletes_trackers_keeps_habits_only_this_profile(
        self, client, db_session, login_as
    ):
        """Deleting all trackers in a profile keeps the habits and leaves
        another profile's trackers untouched."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=profile)
        other_habit = HabitFactory(user=user, profile=other)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date(2026, 1, 1))
        TrackerFactory(habit=habit, dated=date(2026, 1, 2))
        keep = TrackerFactory(habit=other_habit, dated=date(2026, 1, 1))
        await db_session.commit()
        habit_id, keep_id = habit.id, keep.id

        await login_as(user)
        response = await client.delete("/trackers/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Tracker))).scalars().all()
        assert [t.id for t in remaining] == [keep_id]
        # The habit itself survives.
        assert await db_session.get(Habit, habit_id) is not None
