"""Tests for authorization and access control (HTTP-level behavior).

Exercises admin/owner access rules through the API. Unit tests of the
underlying callables (core/dependencies.py) live in test_dependencies.py.
"""

from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestAdminAccess:
    """Tests for admin access rights."""

    async def test_admin_can_access_all_users(self, client, db_session, login_as):
        """Admin can view all users."""
        admin = AdminUserFactory()
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        await login_as(admin)

        # Can access user1
        response = await client.get(f"/users/{user1.id}")
        assert response.status_code == 200

        # Can access user2
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 200

    async def test_admin_can_modify_all_users(self, client, db_session, login_as):
        """Admin can update any user."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        await login_as(admin)

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "AdminModified"},
        )
        assert response.status_code == 200
        assert response.json()["first_name"] == "AdminModified"

    async def test_admin_can_delete_any_user(self, client, db_session, login_as):
        """Admin can delete any user."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        await login_as(admin)

        response = await client.delete(f"/users/{user.id}")
        assert response.status_code == 200

    async def test_admin_can_access_all_habits(self, client, db_session, login_as):
        """Admin can view all habits."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200

    async def test_admin_can_modify_all_habits(self, client, db_session, login_as):
        """Admin can update any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(admin)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "AdminModified"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "AdminModified"

    async def test_admin_can_access_all_trackers(self, client, db_session, login_as):
        """Admin can view all trackers."""
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


class TestRegularUserAccess:
    """Tests for regular user access rights."""

    async def test_user_can_only_see_own_data(self, client, db_session, login_as):
        """User sees only their own data."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        await login_as(user1)

        # Can see own profile
        response = await client.get(f"/users/{user1.id}")
        assert response.status_code == 200

        # Cannot see other user's profile
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_user_cannot_access_other_habits(self, client, db_session, login_as):
        """User denied access to other's habits."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_user_cannot_modify_other_habits(self, client, db_session, login_as):
        """User denied modification of other's habits."""
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

    async def test_user_cannot_access_other_trackers(
        self, client, db_session, login_as
    ):
        """User denied access to other's trackers."""
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

    async def test_user_cannot_modify_other_trackers(
        self, client, db_session, login_as
    ):
        """User denied modification of other's trackers."""
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


class TestAdminDependency:
    """Tests for admin dependency."""

    async def test_admin_access_granted(self, client, db_session, login_as):
        """Admin users get access to admin endpoints."""
        admin = AdminUserFactory()
        await db_session.commit()

        await login_as(admin)

        # Admin can list all users
        response = await client.get("/users/")
        assert response.status_code == 200

    async def test_non_admin_restricted(self, client, db_session, login_as):
        """Non-admin users are restricted from admin endpoints."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # Non-admin cannot delete other users
        response = await client.delete(f"/users/{other_user.id}")
        assert response.status_code == 403


class TestOwnerDependency:
    """Tests for owner authorization dependency."""

    async def test_owner_can_access_own_resource(self, client, db_session, login_as):
        """Owner can access their own resources."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # Create habit
        create_response = await client.post(
            "/habits/",
            json={
                "name": "My Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        habit_id = create_response.json()["id"]

        # Owner can access
        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 200

    async def test_non_owner_cannot_access_resource(self, client, db_session, login_as):
        """Non-owner cannot access others' resources."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # User1 creates habit
        await login_as(user1)

        create_response = await client.post(
            "/habits/",
            json={
                "name": "User1 Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user1.profiles[0].id,
            },
        )
        habit_id = create_response.json()["id"]

        # User2 tries to access
        await login_as(user2)

        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 403

    async def test_admin_can_access_any_resource(self, client, db_session, login_as):
        """Admin can access any user's resources."""
        user = UserFactory()
        admin = AdminUserFactory()
        await db_session.commit()

        # User creates habit
        await login_as(user)

        create_response = await client.post(
            "/habits/",
            json={
                "name": "User Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        habit_id = create_response.json()["id"]

        # Admin accesses
        await login_as(admin)

        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 200
