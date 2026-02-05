"""Tests for habit management endpoints."""

from datetime import date, timedelta

from sqlalchemy import select

from habit_tracker.schemas.db_models import Habit, Tracker
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestCreateHabit:
    """Tests for POST /habits/ endpoint."""

    async def test_create_habit_basic(self, client, db_session, setup_factories):
        """Create habit with minimal required fields."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_all_fields(self, client, db_session, setup_factories):
        """Create habit with all optional fields."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_auto_assigns_user(
        self, client, db_session, setup_factories
    ):
        """Verify habit is assigned to current user."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_invalid_color(
        self, client, db_session, setup_factories
    ):
        """Reject invalid color format (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_negative_frequency(
        self, client, db_session, setup_factories
    ):
        """Reject negative frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_negative_range(
        self, client, db_session, setup_factories
    ):
        """Reject negative range (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_zero_frequency(
        self, client, db_session, setup_factories
    ):
        """Reject zero frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_zero_range(self, client, db_session, setup_factories):
        """Reject zero range (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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
        self, client, db_session, setup_factories
    ):
        """Reject missing required fields (422)."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_with_sort_order(
        self, client, db_session, setup_factories
    ):
        """Create habit with custom sort order."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_create_habit_archived_flag(
        self, client, db_session, setup_factories
    ):
        """Create habit with archived flag."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_get_own_habit(self, client, db_session, setup_factories):
        """User can retrieve their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="My Habit", color="#123456")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == habit.id
        assert data["name"] == "My Habit"

    async def test_get_other_user_habit(self, client, db_session, setup_factories):
        """User cannot access other user's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_get_habit_as_admin(self, client, db_session, setup_factories):
        """Admin can access any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200

    async def test_get_nonexistent_habit(self, client, db_session, setup_factories):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/habits/99999")
        assert response.status_code == 404

    async def test_get_habit_includes_today_status(
        self, client, db_session, setup_factories
    ):
        """Verify completed_today and skipped_today fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), completed=True, skipped=False)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is True
        assert data["skipped_today"] is False

    async def test_get_habit_today_status_with_tracker(
        self, client, db_session, setup_factories
    ):
        """Verify status when tracker exists for today."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), completed=False, skipped=True)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is True

    async def test_get_habit_today_status_without_tracker(
        self, client, db_session, setup_factories
    ):
        """Verify default false when no tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is False


class TestUpdateHabitPut:
    """Tests for PUT /habits/{habit_id} endpoint."""

    async def test_update_own_habit_put(self, client, db_session, setup_factories):
        """User can update their own habit (full update)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_other_user_habit_put(
        self, client, db_session, setup_factories
    ):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_habit_all_fields_put(
        self, client, db_session, setup_factories
    ):
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_habit_color_put(self, client, db_session, setup_factories):
        """Update habit color."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, color="#000000")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_habit_frequency_range_put(
        self, client, db_session, setup_factories
    ):
        """Update frequency and range."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_habit_archived_put(self, client, db_session, setup_factories):
        """Archive/unarchive habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, archived=False)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_nonexistent_habit_put(
        self, client, db_session, setup_factories
    ):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_update_habit_single_field_patch(
        self, client, db_session, setup_factories
    ):
        """Update only one field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Patched"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Patched"

    async def test_update_habit_multiple_fields_patch(
        self, client, db_session, setup_factories
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Multi", "question": "Multi question?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Multi"
        assert data["question"] == "Multi question?"

    async def test_update_habit_name_patch(self, client, db_session, setup_factories):
        """Update habit name."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original Name")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_update_habit_question_patch(
        self, client, db_session, setup_factories
    ):
        """Update habit question."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"question": "New question?"},
        )
        assert response.status_code == 200
        assert response.json()["question"] == "New question?"

    async def test_update_habit_notes_patch(self, client, db_session, setup_factories):
        """Update habit notes."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, notes="Original notes")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"notes": "Updated notes"},
        )
        assert response.status_code == 200
        assert response.json()["notes"] == "Updated notes"

    async def test_update_habit_reminder_patch(
        self, client, db_session, setup_factories
    ):
        """Toggle reminder setting."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, reminder=False)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"reminder": True},
        )
        assert response.status_code == 200
        assert response.json()["reminder"] is True

    async def test_update_habit_sort_order_patch(
        self, client, db_session, setup_factories
    ):
        """Update sort order."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=0)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"sort_order": 50},
        )
        assert response.status_code == 200
        assert response.json()["sort_order"] == 50

    async def test_update_other_user_habit_patch(
        self, client, db_session, setup_factories
    ):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteHabit:
    """Tests for DELETE /habits/{habit_id} endpoint."""

    async def test_delete_own_habit(self, client, db_session, setup_factories):
        """User can delete their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Habit).filter(Habit.id == habit_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_habit(self, client, db_session, setup_factories):
        """User cannot delete other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_delete_habit_as_admin(self, client, db_session, setup_factories):
        """Admin can delete any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

    async def test_delete_nonexistent_habit(self, client, db_session, setup_factories):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete("/habits/99999")
        assert response.status_code == 404

    async def test_delete_habit_cascades_to_trackers(
        self, client, db_session, setup_factories
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None


class TestListHabitTrackers:
    """Tests for GET /habits/{habit_id}/trackers endpoint."""

    async def test_list_habit_trackers_basic(self, client, db_session, setup_factories):
        """List trackers for a habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today())
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 2

    async def test_list_habit_trackers_pagination(
        self, client, db_session, setup_factories
    ):
        """Verify pagination with limit parameter."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 3
        assert data["limit"] == 3

    async def test_list_habit_trackers_order(self, client, db_session, setup_factories):
        """Verify trackers ordered by date descending."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=2))
        TrackerFactory(habit=habit, dated=date.today())
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        trackers = response.json()["trackers"]

        # Should be ordered by date descending
        dates = [t["dated"] for t in trackers]
        assert dates == sorted(dates, reverse=True)

    async def test_list_habit_trackers_empty(self, client, db_session, setup_factories):
        """Return empty list for habit with no trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trackers"]) == 0
        assert data["total"] == 0

    async def test_list_habit_trackers_unauthorized(
        self, client, db_session, setup_factories
    ):
        """User cannot access other's habit trackers (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        TrackerFactory(habit=habit)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 403

    async def test_list_habit_trackers_default_limit(
        self, client, db_session, setup_factories
    ):
        """Verify default limit of 5."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert len(data["trackers"]) == 5

    async def test_list_habit_trackers_custom_limit(
        self, client, db_session, setup_factories
    ):
        """Test with custom limit value."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers?limit=7")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 7
        assert len(data["trackers"]) == 7

    async def test_list_habit_trackers_returns_total(
        self, client, db_session, setup_factories
    ):
        """Verify total count in response."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(8):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3  # Note: current impl returns len of returned items


class TestListHabitTrackersLite:
    """Tests for GET /habits/{habit_id}/trackers/lite endpoint with date-based pagination."""

    async def test_list_trackers_lite_default_params(
        self, client, db_session, setup_factories
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert data["days"] == 42
        assert data["end_date"] == date.today().isoformat()
        assert data["has_previous"] is False

    async def test_list_trackers_lite_with_end_date(
        self, client, db_session, setup_factories
    ):
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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
        self, client, db_session, setup_factories
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["has_previous"] is True
        assert data["total"] == 5  # Only recent 5 within the 7-day window

    async def test_list_trackers_lite_has_previous_false(
        self, client, db_session, setup_factories
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=42")
        assert response.status_code == 200
        data = response.json()
        assert data["has_previous"] is False

    async def test_list_trackers_lite_pagination(
        self, client, db_session, setup_factories
    ):
        """Test paginating through trackers with different end_dates."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create trackers spanning 60 days
        for i in range(60):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_list_trackers_lite_empty_range(
        self, client, db_session, setup_factories
    ):
        """Returns empty list when no trackers in date range."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Create tracker outside the range
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=100))
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite?days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["trackers"]) == 0
        assert data["has_previous"] is True  # There is an older tracker

    async def test_list_trackers_lite_unauthorized(
        self, client, db_session, setup_factories
    ):
        """User cannot list other user's trackers (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 403

    async def test_list_trackers_lite_nonexistent_habit(
        self, client, db_session, setup_factories
    ):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/habits/99999/trackers/lite")
        assert response.status_code == 404

    async def test_list_trackers_lite_has_note_flag(
        self, client, db_session, setup_factories
    ):
        """Verify has_note flag is correctly set."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), note="Has a note")
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=1), note="")
        TrackerFactory(habit=habit, dated=date.today() - timedelta(days=2), note=None)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers/lite")
        assert response.status_code == 200
        data = response.json()
        trackers = data["trackers"]
        assert len(trackers) == 3
        # Ordered by date descending
        assert trackers[0]["has_note"] is True  # today - has note
        assert trackers[1]["has_note"] is False  # yesterday - empty string
        assert trackers[2]["has_note"] is False  # 2 days ago - None


class TestGetHabitKPIs:
    """Tests for GET /habits/{habit_id}/kpis endpoint."""

    async def test_get_habit_kpis_new_habit(self, client, db_session, setup_factories):
        """KPIs for newly created habit (zeros)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_completions"] == 0
        assert data["current_streak"] == 0
        assert data["longest_streak"] == 0

    async def test_get_habit_kpis_current_streak(
        self, client, db_session, setup_factories
    ):
        """Verify current streak calculation."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        # Create 5 consecutive days of completions
        for i in range(5):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
                completed=True,
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["current_streak"] >= 1

    async def test_get_habit_kpis_total_completions(
        self, client, db_session, setup_factories
    ):
        """Verify total completions count."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(7):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
                completed=True,
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_completions"] == 7

    async def test_get_habit_kpis_thirty_day_rate(
        self, client, db_session, setup_factories
    ):
        """Verify 30-day completion rate."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Complete 15 of last 30 days
        for i in range(15):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i * 2),
                completed=True,
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["thirty_day_completion_rate"] >= 0

    async def test_get_habit_kpis_last_completed(
        self, client, db_session, setup_factories
    ):
        """Verify last completed date."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        last_date = date.today() - timedelta(days=3)
        TrackerFactory(habit=habit, dated=last_date, completed=True)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["last_completed_date"] == last_date.isoformat()

    async def test_get_habit_kpis_unauthorized(
        self, client, db_session, setup_factories
    ):
        """User cannot access other's habit KPIs (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/kpis")
        assert response.status_code == 403


class TestGetHabitStreaks:
    """Tests for GET /habits/{habit_id}/streaks endpoint."""

    async def test_get_habit_streaks_empty(self, client, db_session, setup_factories):
        """Empty list for habit with no completions."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    async def test_get_habit_streaks_single_streak(
        self, client, db_session, setup_factories
    ):
        """Single continuous streak."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        for i in range(5):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
                completed=True,
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    async def test_get_habit_streaks_with_skips(
        self, client, db_session, setup_factories
    ):
        """Streaks including skipped days."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), completed=True)
        TrackerFactory(
            habit=habit,
            dated=date.today() - timedelta(days=1),
            completed=False,
            skipped=True,
        )
        TrackerFactory(
            habit=habit, dated=date.today() - timedelta(days=2), completed=True
        )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 200

    async def test_get_habit_streaks_unauthorized(
        self, client, db_session, setup_factories
    ):
        """User cannot access other's habit streaks (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/streaks")
        assert response.status_code == 403


class TestSortHabits:
    """Tests for PUT /habits/sort endpoint."""

    async def test_sort_habits_basic(self, client, db_session, setup_factories):
        """Successfully reorder multiple habits."""
        user = UserFactory()
        await db_session.commit()

        # Create habits with initial sort orders
        habit1 = HabitFactory(user=user, name="Habit 1")
        habit2 = HabitFactory(user=user, name="Habit 2")
        habit3 = HabitFactory(user=user, name="Habit 3")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

        # habit3 sent first gets sort_order 2, habit1 gets 1, habit2 gets 0
        assert habit3.sort_order == 2
        assert habit1.sort_order == 1
        assert habit2.sort_order == 0

    async def test_sort_habits_archived(self, client, db_session, setup_factories):
        """Archived habits preserve their sort_order when sorting is applied."""
        user = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user, name="Active Habit", archived=False)
        habit2 = HabitFactory(
            user=user, name="Archived Habit", archived=True, sort_order=0
        )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            "/habits/sort",
            json=[habit2.id, habit1.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit1)
        await db_session.refresh(habit2)

        # Active habit gets sort_order: total(2) - 1 = 1, but 0 is taken by archived, so stays 1
        assert habit1.sort_order == 1
        # Archived habit preserves its original sort_order
        assert habit2.sort_order == 0

    async def test_sort_habits_archived_preserves_position(
        self, client, db_session, setup_factories
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

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

        # Active habits get sort_order starting from total(4) - 1 = 3
        # Skipping 2 because B (archived, not in request) has sort_order=2
        # A: 3, C: 1 (skip 2), D: 0
        # When B is unarchived, order by sort_order desc: A(3), B(2), C(1), D(0)
        assert habit_a.sort_order == 3
        assert habit_b.sort_order == 2  # Preserved
        assert habit_c.sort_order == 1  # Skipped 2
        assert habit_d.sort_order == 0

    async def test_sort_habits_single_habit(self, client, db_session, setup_factories):
        """Sorting a single habit should work."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=5)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit)
        assert habit.sort_order == 0

    async def test_sort_habits_empty_list(self, client, db_session, setup_factories):
        """Sorting empty list returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put("/habits/sort", json=[])
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"].lower()

    async def test_sort_habits_duplicate_ids(self, client, db_session, setup_factories):
        """Sorting with duplicate habit IDs returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put("/habits/sort", json=[habit.id, habit.id])
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    async def test_sort_habits_not_found(self, client, db_session, setup_factories):
        """Cannot sort non-existent habit (404)."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put("/habits/sort", json=[99999])
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_sort_habits_unauthorized(self, client, db_session, setup_factories):
        """User cannot sort other user's habits (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 403

    async def test_sort_habits_mixed_ownership(
        self, client, db_session, setup_factories
    ):
        """Cannot sort habits when some belong to other users (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user1)
        habit2 = HabitFactory(user=user2)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            "/habits/sort",
            json=[
                habit1.id,
                habit2.id,
            ],
        )
        assert response.status_code == 403

    async def test_sort_habits_unauthenticated(
        self, client, db_session, setup_factories
    ):
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
