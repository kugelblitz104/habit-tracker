"""Tests for authorization and access control."""

import pytest

from habit_tracker.core.dependencies import (
    authorize_resource_access,
    is_admin_or_owner,
    require_admin,
)
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestAdminAccess:
    """Tests for admin access rights."""

    async def test_admin_can_access_all_users(
        self, client, db_session, setup_factories
    ):
        """Admin can view all users."""
        admin = AdminUserFactory()
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Can access user1
        response = await client.get(f"/users/{user1.id}")
        assert response.status_code == 200

        # Can access user2
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 200

    async def test_admin_can_modify_all_users(
        self, client, db_session, setup_factories
    ):
        """Admin can update any user."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/users/{user.id}",
            json={"first_name": "AdminModified"},
        )
        assert response.status_code == 200
        assert response.json()["first_name"] == "AdminModified"

    async def test_admin_can_delete_any_user(self, client, db_session, setup_factories):
        """Admin can delete any user."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.delete(f"/users/{user.id}")
        assert response.status_code == 200

    async def test_admin_can_access_all_habits(
        self, client, db_session, setup_factories
    ):
        """Admin can view all habits."""
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

    async def test_admin_can_modify_all_habits(
        self, client, db_session, setup_factories
    ):
        """Admin can update any habit."""
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

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "AdminModified"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "AdminModified"

    async def test_admin_can_access_all_trackers(
        self, client, db_session, setup_factories
    ):
        """Admin can view all trackers."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 200


class TestRegularUserAccess:
    """Tests for regular user access rights."""

    async def test_user_can_only_see_own_data(
        self, client, db_session, setup_factories
    ):
        """User sees only their own data."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Can see own profile
        response = await client.get(f"/users/{user1.id}")
        assert response.status_code == 200

        # Cannot see other user's profile
        response = await client.get(f"/users/{user2.id}")
        assert response.status_code == 403

    async def test_user_cannot_access_other_habits(
        self, client, db_session, setup_factories
    ):
        """User denied access to other's habits."""
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

    async def test_user_cannot_modify_other_habits(
        self, client, db_session, setup_factories
    ):
        """User denied modification of other's habits."""
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

    async def test_user_cannot_access_other_trackers(
        self, client, db_session, setup_factories
    ):
        """User denied access to other's trackers."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 403

    async def test_user_cannot_modify_other_trackers(
        self, client, db_session, setup_factories
    ):
        """User denied modification of other's trackers."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": "Hacked"},
        )
        assert response.status_code == 403


class TestAuthorizationHelperFunctions:
    """Tests for authorization helper functions."""

    async def test_authorize_resource_access_owner(self, db_session, setup_factories):
        """Owner can access their resources."""
        user = UserFactory()
        await db_session.commit()

        # Should not raise exception
        authorize_resource_access(user, user.id, "test")

    async def test_authorize_resource_access_admin(self, db_session, setup_factories):
        """Admin can access any resource."""
        admin = AdminUserFactory()
        other_user = UserFactory()
        await db_session.commit()

        # Should not raise exception
        authorize_resource_access(admin, other_user.id, "test")

    async def test_authorize_resource_access_unauthorized(
        self, db_session, setup_factories
    ):
        """Unauthorized access raises 403."""
        from fastapi import HTTPException

        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            authorize_resource_access(user1, user2.id, "test")
        assert exc_info.value.status_code == 403

    async def test_is_admin_or_owner_as_admin(self, db_session, setup_factories):
        """Admin check returns true."""
        admin = AdminUserFactory()
        other_user = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(admin, other_user.id)
        assert result is True

    async def test_is_admin_or_owner_as_owner(self, db_session, setup_factories):
        """Owner check returns true."""
        user = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(user, user.id)
        assert result is True

    async def test_is_admin_or_owner_neither(self, db_session, setup_factories):
        """Neither admin nor owner returns false."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(user1, user2.id)
        assert result is False

    async def test_require_admin_with_admin(self, db_session, setup_factories):
        """Admin passes admin requirement."""
        admin = AdminUserFactory()
        await db_session.commit()

        result = require_admin(admin)
        assert result == admin

    async def test_require_admin_with_regular_user(self, db_session, setup_factories):
        """Regular user fails admin requirement."""
        from fastapi import HTTPException

        user = UserFactory()
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            require_admin(user)
        assert exc_info.value.status_code == 403
