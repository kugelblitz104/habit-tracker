"""Tests for user management endpoints."""

from sqlalchemy import select

from habit_tracker.schemas.db_models import Habit, Tracker, User
from tests.factories import AdminUserFactory, HabitFactory, TrackerFactory, UserFactory


class TestGetUser:
    """Tests for GET /users/{user_id} endpoint."""

    async def test_get_own_user(self, client, db_session, setup_factories):
        """User can retrieve their own profile."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user.id
        assert data["username"] == user.username
        assert data["email"] == user.email

    async def test_get_other_user_as_regular(self, client, db_session, setup_factories):
        """Regular user cannot access other user profiles (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try to access user2's profile
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_get_other_user_as_admin(self, client, db_session, setup_factories):
        """Admin can access any user profile."""
        admin = AdminUserFactory()
        regular_user = UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Access regular user's profile
        response = await client.get(f"/users/{regular_user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == regular_user.id

    async def test_get_nonexistent_user(self, client, db_session, setup_factories):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/99999")
        assert response.status_code == 404

    async def test_get_user_without_auth(self, client, db_session, setup_factories):
        """Reject request without authentication token (401)."""
        user = UserFactory()
        await db_session.commit()

        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 401


class TestListUsers:
    """Tests for GET /users/ endpoint."""

    async def test_list_users_as_regular_user(
        self, client, db_session, setup_factories
    ):
        """Regular user sees only themselves."""
        user1 = UserFactory()
        UserFactory()
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["users"]) == 1
        assert data["users"][0]["id"] == user1.id

    async def test_list_users_as_admin(self, client, db_session, setup_factories):
        """Admin sees all users."""
        admin = AdminUserFactory()
        UserFactory()
        UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3  # admin + 2 users

    async def test_list_users_pagination(self, client, db_session, setup_factories):
        """Verify pagination with limit parameter."""
        admin = AdminUserFactory()
        for _ in range(10):
            UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["users"]) == 3
        assert data["total"] == 11  # admin + 10 users
        assert data["limit"] == 3

    async def test_list_users_default_limit(self, client, db_session, setup_factories):
        """Verify default limit of 5."""
        admin = AdminUserFactory()
        for _ in range(10):
            UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert len(data["users"]) == 5

    async def test_list_users_max_limit(self, client, db_session, setup_factories):
        """Verify max limit of 100."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Requesting beyond max should be rejected
        response = await client.get("/users/?limit=101")
        assert response.status_code == 422  # Validation error

    async def test_list_users_returns_total_count(
        self, client, db_session, setup_factories
    ):
        """Verify total count in response."""
        admin = AdminUserFactory()
        for _ in range(7):
            UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 8  # admin + 7 users
        assert len(data["users"]) == 3


class TestUpdateUserPut:
    """Tests for PUT /users/{user_id} endpoint."""

    async def test_update_own_user_put(self, client, db_session, setup_factories):
        """User can update their own profile (full update)."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "updateduser",
                "first_name": "Updated",
                "last_name": "User",
                "email": "updated@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "updateduser"
        assert data["first_name"] == "Updated"
        assert data["last_name"] == "User"
        assert data["email"] == "updated@example.com"

    async def test_update_other_user_as_regular_put(
        self, client, db_session, setup_factories
    ):
        """Regular user cannot update other profiles (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try to update user2's profile
        response = await client.put(
            f"/users/{user2.id}",
            json={
                "username": "hacked",
                "first_name": "Hacked",
                "last_name": "User",
                "email": "hacked@example.com",
            },
        )
        assert response.status_code == 403

    async def test_update_user_as_admin_put(self, client, db_session, setup_factories):
        """Admin can update any user profile."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "adminupdated",
                "first_name": "Admin",
                "last_name": "Updated",
                "email": "adminupdated@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "adminupdated"

    async def test_update_user_all_fields_put(
        self, client, db_session, setup_factories
    ):
        """Verify all fields are updated."""
        user = UserFactory(
            username="original",
            first_name="Original",
            last_name="Name",
            email="original@example.com",
        )
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            f"/users/{user.id}",
            json={
                "username": "newusername",
                "first_name": "New",
                "last_name": "Name",
                "email": "new@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newusername"
        assert data["first_name"] == "New"
        assert data["last_name"] == "Name"
        assert data["email"] == "new@example.com"

    async def test_update_nonexistent_user_put(
        self, client, db_session, setup_factories
    ):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.put(
            "/users/99999",
            json={
                "username": "nonexistent",
                "first_name": "Non",
                "last_name": "Existent",
                "email": "nonexistent@example.com",
            },
        )
        assert response.status_code == 404


class TestUpdateUserPatch:
    """Tests for PATCH /users/{user_id} endpoint."""

    async def test_update_own_user_patch(self, client, db_session, setup_factories):
        """User can partially update their profile."""
        user = UserFactory(username="patchuser", first_name="Original")
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "Patched"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Patched"
        assert data["username"] == "patchuser"  # Unchanged

    async def test_update_user_single_field_patch(
        self, client, db_session, setup_factories
    ):
        """Update only one field."""
        user = UserFactory()
        original_username = user.username
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "SingleFieldUpdate"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "SingleFieldUpdate"
        assert data["username"] == original_username

    async def test_update_user_multiple_fields_patch(
        self, client, db_session, setup_factories
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "Multi", "last_name": "Update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Multi"
        assert data["last_name"] == "Update"

    async def test_update_user_username_patch(
        self, client, db_session, setup_factories
    ):
        """Update username."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"username": "newusernamepatched"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newusernamepatched"

    async def test_update_user_email_patch(self, client, db_session, setup_factories):
        """Update email."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"email": "newemail@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "newemail@example.com"

    async def test_update_user_names_patch(self, client, db_session, setup_factories):
        """Update first and last name."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "NewFirst", "last_name": "NewLast"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "NewFirst"
        assert data["last_name"] == "NewLast"

    async def test_update_other_user_as_regular_patch(
        self, client, db_session, setup_factories
    ):
        """Regular user cannot update others (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try to update user2
        response = await client.patch(
            f"/users/{user2.id}",
            json={"first_name": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteUser:
    """Tests for DELETE /users/{user_id} endpoint."""

    async def test_delete_own_user(self, client, db_session, setup_factories):
        """User can delete their own account."""
        user = UserFactory()
        await db_session.commit()
        user_id = user.id

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify user was deleted
        result = await db_session.execute(select(User).filter(User.id == user_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_as_regular(
        self, client, db_session, setup_factories
    ):
        """Regular user cannot delete other accounts (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try to delete user2
        response = await client.delete(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_delete_user_as_admin(self, client, db_session, setup_factories):
        """Admin can delete any user account."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()
        user_id = user.id

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify user was deleted
        result = await db_session.execute(select(User).filter(User.id == user_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_nonexistent_user(self, client, db_session, setup_factories):
        """Return 404 for non-existent user."""
        admin = AdminUserFactory()
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete("/users/99999")
        assert response.status_code == 404

    async def test_delete_user_cascades_to_habits(
        self, client, db_session, setup_factories
    ):
        """Verify habits are deleted with user."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        user_id = user.id
        habit_id = habit.id

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify habit was also deleted
        result = await db_session.execute(select(Habit).filter(Habit.id == habit_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_user_cascades_to_trackers(
        self, client, db_session, setup_factories
    ):
        """Verify trackers are deleted with user."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        user_id = user.id
        tracker_id = tracker.id

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/users/{user_id}")
        assert response.status_code == 200

        # Verify tracker was also deleted
        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None


class TestListUserHabits:
    """Tests for GET /users/{user_id}/habits endpoint."""

    async def test_list_own_habits(self, client, db_session, setup_factories):
        """User can list their own habits."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user, name="Habit 1")
        HabitFactory(user=user, name="Habit 2")
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["habits"]) == 2

    async def test_list_other_user_habits_as_regular(
        self, client, db_session, setup_factories
    ):
        """Regular user cannot list others' habits (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        HabitFactory(user=user2)
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try to list user2's habits
        response = await client.get(f"/users/{user2.id}/habits")
        assert response.status_code == 403

    async def test_list_user_habits_as_admin(self, client, db_session, setup_factories):
        """Admin can list any user's habits."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user, name="User Habit")
        await db_session.commit()

        # Login as admin
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    async def test_list_user_habits_pagination(
        self, client, db_session, setup_factories
    ):
        """Verify pagination with limit parameter."""
        user = UserFactory()
        await db_session.commit()

        for i in range(10):
            HabitFactory(user=user, name=f"Habit {i}")
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["habits"]) == 3
        assert data["total"] == 10
        assert data["limit"] == 3

    async def test_list_user_habits_includes_today_status(
        self, client, db_session, setup_factories
    ):
        """Verify completed_today and skipped_today fields."""
        from datetime import date

        user = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user, name="Completed Habit")
        habit2 = HabitFactory(user=user, name="Skipped Habit")
        HabitFactory(user=user, name="No Tracker Habit")
        await db_session.commit()

        # Create trackers for today
        TrackerFactory(habit=habit1, dated=date.today(), completed=True, skipped=False)
        TrackerFactory(habit=habit2, dated=date.today(), completed=False, skipped=True)
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()

        habits_by_name = {h["name"]: h for h in data["habits"]}

        assert habits_by_name["Completed Habit"]["completed_today"] is True
        assert habits_by_name["Completed Habit"]["skipped_today"] is False

        assert habits_by_name["Skipped Habit"]["completed_today"] is False
        assert habits_by_name["Skipped Habit"]["skipped_today"] is True

        assert habits_by_name["No Tracker Habit"]["completed_today"] is False
        assert habits_by_name["No Tracker Habit"]["skipped_today"] is False

    async def test_list_user_habits_returns_total_count(
        self, client, db_session, setup_factories
    ):
        """Verify total count in response."""
        user = UserFactory()
        await db_session.commit()

        for i in range(8):
            HabitFactory(user=user)
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 8
        assert len(data["habits"]) == 3

    async def test_list_user_habits_empty(self, client, db_session, setup_factories):
        """Return empty list for user with no habits."""
        user = UserFactory()
        await db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["habits"]) == 0
