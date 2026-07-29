"""Tests for habit management endpoints."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

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


class TestCreateHabit:
    """Tests for POST /habits/ endpoint."""

    async def test_create_habit_basic(self, client, db_session, login_as):
        """Create habit with minimal required fields."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Drink Water",
                "question": "Did you drink 8 glasses?",
                "color": "#00FF00",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Drink Water"
        assert data["question"] == "Did you drink 8 glasses?"
        assert data["color"] == "#00FF00"

    async def test_create_habit_all_fields(self, client, db_session, login_as):
        """Create habit with all optional fields."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Exercise",
                "question": "Did you exercise today?",
                "color": "#FF0000",
                "frequency": 5,
                "range": 7,
                "reminder": True,
                "notes": "Morning workout routine",
                "archived": False,
                "sort_order": 10,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Exercise"
        assert data["frequency"] == 5
        assert data["range"] == 7
        assert data["reminder"] is True
        assert data["notes"] == "Morning workout routine"
        assert data["sort_order"] == 10

    async def test_create_habit_auto_assigns_user(self, client, db_session, login_as):
        """Verify habit is assigned to current user."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201
        habit_id = response.json()["id"]

        habit = await db_session.get(Habit, habit_id)
        assert habit.user_id == user.id

    async def test_create_habit_invalid_color(self, client, db_session, login_as):
        """Reject invalid color format (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "blue",  # Invalid - not hex
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_negative_frequency(self, client, db_session, login_as):
        """Reject negative frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": -1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_negative_range(self, client, db_session, login_as):
        """Reject negative range (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": -1,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_zero_frequency(self, client, db_session, login_as):
        """Reject zero frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 0,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_zero_range(self, client, db_session, login_as):
        """Reject zero range (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 0,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_missing_required_fields(
        self, client, db_session, login_as
    ):
        """Reject missing required fields (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # Missing name
        response = await client.post(
            "/habits/",
            json={
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_with_sort_order(self, client, db_session, login_as):
        """Create habit with custom sort order."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Sorted Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "sort_order": 99,
            },
        )
        assert response.status_code == 201
        assert response.json()["sort_order"] == 99

    async def test_create_habit_archived_flag(self, client, db_session, login_as):
        """Create habit with archived flag."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Archived Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "archived": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["archived"] is True


class TestGetHabit:
    """Tests for GET /habits/{habit_id} endpoint."""

    async def test_get_own_habit(self, client, db_session, login_as):
        """User can retrieve their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="My Habit", color="#123456")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == habit.id
        assert data["name"] == "My Habit"

    async def test_get_other_user_habit(self, client, db_session, login_as):
        """User cannot access other user's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_get_habit_as_admin(self, client, db_session, login_as):
        """Admin can access any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200

    async def test_get_nonexistent_habit(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/99999")
        assert response.status_code == 404

    async def test_get_habit_includes_today_status(self, client, db_session, login_as):
        """Verify completed_today and skipped_today fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.COMPLETED)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is True
        assert data["skipped_today"] is False

    async def test_get_habit_today_status_with_tracker(
        self, client, db_session, login_as
    ):
        """Verify status when tracker exists for today."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.SKIPPED)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is True

    async def test_get_habit_today_status_without_tracker(
        self, client, db_session, login_as
    ):
        """Verify default false when no tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is False

    async def test_get_habit_today_status_honors_tz(self, client, db_session, login_as):
        """completed_today is computed against "today" in the requested zone.

        Etc/GMT+12 (UTC-12) and Etc/GMT-14 (UTC+14) are 26 hours apart, so
        their calendar dates always differ. A tracker dated "today" in one
        zone is therefore completed_today only for that zone, regardless of
        when the test runs.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tz_name, other_tz_name = "Etc/GMT-14", "Etc/GMT+12"
        expected_today = datetime.now(ZoneInfo(tz_name)).date()
        TrackerFactory(
            habit=habit, dated=expected_today, status=TrackerStatus.COMPLETED
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}", params={"tz": tz_name})
        assert response.status_code == 200
        assert response.json()["completed_today"] is True

        response = await client.get(f"/habits/{habit.id}", params={"tz": other_tz_name})
        assert response.status_code == 200
        assert response.json()["completed_today"] is False

    async def test_get_habit_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}", params={"tz": "Not/AZone"})
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]


class TestUpdateHabitPut:
    """Tests for PUT /habits/{habit_id} endpoint."""

    async def test_update_own_habit_put(self, client, db_session, login_as):
        """User can update their own habit (full update)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "Updated",
                "question": "Updated question?",
                "color": "#FFFFFF",
                "frequency": 2,
                "range": 3,
                "reminder": True,
                "notes": "Updated notes",
                "archived": False,
                "sort_order": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated"
        assert data["question"] == "Updated question?"

    async def test_update_other_user_habit_put(self, client, db_session, login_as):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "Hacked",
                "question": "Hacked?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 403

    async def test_update_habit_all_fields_put(self, client, db_session, login_as):
        """Verify all fields are updated."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(
            user=user,
            name="Original",
            question="Original?",
            color="#000000",
            frequency=1,
            range=1,
            reminder=False,
            notes="Original notes",
            archived=False,
            sort_order=0,
        )
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "New Name",
                "question": "New Question?",
                "color": "#AABBCC",
                "frequency": 5,
                "range": 7,
                "reminder": True,
                "notes": "New notes",
                "archived": True,
                "sort_order": 10,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["question"] == "New Question?"
        assert data["color"] == "#AABBCC"
        assert data["frequency"] == 5
        assert data["range"] == 7
        assert data["reminder"] is True
        assert data["notes"] == "New notes"
        assert data["archived"] is True
        assert data["sort_order"] == 10

    async def test_update_habit_color_put(self, client, db_session, login_as):
        """Update habit color."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, color="#000000")
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": "#FF5733",
                "frequency": habit.frequency,
                "range": habit.range,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": habit.archived,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        assert response.json()["color"] == "#FF5733"

    async def test_update_habit_frequency_range_put(self, client, db_session, login_as):
        """Update frequency and range."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": habit.color,
                "frequency": 5,
                "range": 7,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": habit.archived,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["frequency"] == 5
        assert data["range"] == 7

    async def test_update_habit_archived_put(self, client, db_session, login_as):
        """Archive/unarchive habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, archived=False)
        await db_session.commit()

        await login_as(user)

        # Archive
        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": habit.color,
                "frequency": habit.frequency,
                "range": habit.range,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": True,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        assert response.json()["archived"] is True

    async def test_update_nonexistent_habit_put(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/99999",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "notes": "",
                "reminder": False,
                "archived": False,
                "sort_order": 0,
            },
        )
        assert response.status_code == 404


class TestUpdateHabitPatch:
    """Tests for PATCH /habits/{habit_id} endpoint."""

    async def test_update_habit_single_field_patch(self, client, db_session, login_as):
        """Update only one field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Patched"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Patched"

    async def test_update_habit_multiple_fields_patch(
        self, client, db_session, login_as
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Multi", "question": "Multi question?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Multi"
        assert data["question"] == "Multi question?"

    async def test_update_habit_name_patch(self, client, db_session, login_as):
        """Update habit name."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original Name")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_update_habit_question_patch(self, client, db_session, login_as):
        """Update habit question."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"question": "New question?"},
        )
        assert response.status_code == 200
        assert response.json()["question"] == "New question?"

    async def test_update_habit_notes_patch(self, client, db_session, login_as):
        """Update habit notes."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, notes="Original notes")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"notes": "Updated notes"},
        )
        assert response.status_code == 200
        assert response.json()["notes"] == "Updated notes"

    async def test_update_habit_reminder_patch(self, client, db_session, login_as):
        """Toggle reminder setting."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, reminder=False)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"reminder": True},
        )
        assert response.status_code == 200
        assert response.json()["reminder"] is True

    async def test_update_habit_sort_order_patch(self, client, db_session, login_as):
        """Update sort order."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=0)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"sort_order": 50},
        )
        assert response.status_code == 200
        assert response.json()["sort_order"] == 50

    async def test_update_other_user_habit_patch(self, client, db_session, login_as):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteHabit:
    """Tests for DELETE /habits/{habit_id} endpoint."""

    async def test_delete_own_habit(self, client, db_session, login_as):
        """User can delete their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        await login_as(user)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Habit).filter(Habit.id == habit_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_habit(self, client, db_session, login_as):
        """User cannot delete other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.delete(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_delete_habit_as_admin(self, client, db_session, login_as):
        """Admin can delete any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        await login_as(admin)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

    async def test_delete_nonexistent_habit(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/habits/99999")
        assert response.status_code == 404

    async def test_delete_habit_cascades_to_trackers(
        self, client, db_session, login_as
    ):
        """Verify trackers are deleted with habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        habit_id = habit.id
        tracker_id = tracker.id

        await login_as(user)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None


class TestSortHabits:
    """Tests for PUT /habits/sort endpoint."""

    async def test_sort_habits_basic(self, client, db_session, login_as):
        """Successfully reorder multiple habits."""
        user = UserFactory()
        await db_session.commit()

        # Create habits with initial sort orders
        habit1 = HabitFactory(user=user, name="Habit 1")
        habit2 = HabitFactory(user=user, name="Habit 2")
        habit3 = HabitFactory(user=user, name="Habit 3")
        await db_session.commit()

        await login_as(user)

        # Reorder: habit3, habit1, habit2
        response = await client.put(
            "/habits/sort",
            json=[habit3.id, habit1.id, habit2.id],
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Habits sorted successfully"

        # Verify sort_order was updated correctly
        await db_session.refresh(habit1)
        await db_session.refresh(habit2)
        await db_session.refresh(habit3)

        # First ID gets the lowest sort_order (habits display in ascending
        # sort_order): habit3 -> 0, habit1 -> 1, habit2 -> 2
        assert habit3.sort_order == 0
        assert habit1.sort_order == 1
        assert habit2.sort_order == 2

    async def test_sort_habits_archived(self, client, db_session, login_as):
        """Archived habits preserve their sort_order when sorting is applied."""
        user = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user, name="Active Habit", archived=False)
        habit2 = HabitFactory(
            user=user, name="Archived Habit", archived=True, sort_order=5
        )
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/sort",
            json=[habit2.id, habit1.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit1)
        await db_session.refresh(habit2)

        # Only active habits are re-numbered; habit1 is the first (only)
        # active habit in the list so it gets sort_order 0
        assert habit1.sort_order == 0
        # Archived habit preserves its original sort_order
        assert habit2.sort_order == 5

    async def test_sort_habits_archived_preserves_position(
        self, client, db_session, login_as
    ):
        """Archived habits should slot back into their original position when unarchived."""
        user = UserFactory()
        await db_session.commit()

        # Create 4 habits: A, B, C, D with sort_order 3, 2, 1, 0
        habit_a = HabitFactory(user=user, name="A", sort_order=3)
        habit_b = HabitFactory(user=user, name="B", sort_order=2, archived=True)
        habit_c = HabitFactory(user=user, name="C", sort_order=1)
        habit_d = HabitFactory(user=user, name="D", sort_order=0)
        await db_session.commit()

        await login_as(user)

        # Sort only active habits A, C, D (B is archived)
        response = await client.put(
            "/habits/sort",
            json=[habit_a.id, habit_c.id, habit_d.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit_a)
        await db_session.refresh(habit_b)
        await db_session.refresh(habit_c)
        await db_session.refresh(habit_d)

        # Active habits are numbered in request order starting from 0,
        # skipping sort_order values held by archived habits not in the
        # request: A -> 0, C -> 1, D -> 3 (2 is held by archived B).
        # When B is unarchived, ascending order is A(0), C(1), B(2), D(3).
        assert habit_a.sort_order == 0
        assert habit_b.sort_order == 2  # Preserved
        assert habit_c.sort_order == 1
        assert habit_d.sort_order == 3  # Skipped 2

    async def test_sort_habits_single_habit(self, client, db_session, login_as):
        """Sorting a single habit should work."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=5)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit)
        assert habit.sort_order == 0

    async def test_sort_habits_empty_list(self, client, db_session, login_as):
        """Sorting empty list returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[])
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"].lower()

    async def test_sort_habits_duplicate_ids(self, client, db_session, login_as):
        """Sorting with duplicate habit IDs returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[habit.id, habit.id])
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    async def test_sort_habits_not_found(self, client, db_session, login_as):
        """Cannot sort non-existent habit (404)."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[99999])
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_sort_habits_unauthorized(self, client, db_session, login_as):
        """User cannot sort other user's habits (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 403

    async def test_sort_habits_mixed_ownership(self, client, db_session, login_as):
        """Cannot sort habits when some belong to other users (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user1)
        habit2 = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            "/habits/sort",
            json=[
                habit1.id,
                habit2.id,
            ],
        )
        assert response.status_code == 403

    async def test_sort_habits_unauthenticated(self, client, db_session):
        """Unauthenticated users cannot sort habits (401)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 401


class TestDeleteAllHabits:
    """Tests for DELETE /habits/ (bulk delete, profile-scoped)."""

    async def test_deletes_habits_and_trackers_only_this_profile(
        self, client, db_session, login_as
    ):
        """Deleting all habits in a profile also removes their trackers
        (CASCADE) and leaves another profile's habits alone."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=profile)
        HabitFactory(user=user, profile=profile)
        keep = HabitFactory(user=user, profile=other)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        tracker_id = tracker.id

        await login_as(user)
        response = await client.delete("/habits/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Habit))).scalars().all()
        assert [h.id for h in remaining] == [keep.id]
        # Trackers of the deleted habits are gone too (expire first so the
        # check re-reads from the DB rather than the session identity map).
        db_session.expire_all()
        assert await db_session.get(Tracker, tracker_id) is None
