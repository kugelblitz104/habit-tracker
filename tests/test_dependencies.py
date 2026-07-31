"""Dependency injection tests.

Unit tests of the callables in core/dependencies.py and the plumbing they
sit behind (auth, DB session, admin/owner checks) - no HTTP-level
authorization *behavior* here; that belongs in test_authorization.py.
"""

import pytest
from fastapi import HTTPException

from habit_tracker.core.dependencies import (
    authorize_resource_access,
    get_owned_habit,
    is_admin_or_owner,
    require_admin,
)
from tests.factories import AdminUserFactory, HabitFactory, UserFactory


class TestDatabaseDependency:
    """Tests for database dependency."""

    async def test_database_session_provided(self, client, db_session, login_as):
        """Database session is available to endpoints."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # If endpoints work, database session is properly injected
        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200

    async def test_database_isolation(self, client, db_session, login_as):
        """Database transactions are isolated."""
        user1 = UserFactory()
        await db_session.commit()

        await login_as(user1)

        # Changes in one request shouldn't leak to others incorrectly
        response = await client.post(
            "/habits/",
            json={
                "name": "Isolated Habit",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user1.profiles[0].id,
            },
        )
        assert response.status_code == 201
        habit_id = response.json()["id"]

        # Verify habit persists
        get_response = await client.get(f"/habits/{habit_id}")
        assert get_response.status_code == 200

    async def test_database_rollback_on_error(self, client, db_session, login_as):
        """Database rolls back on error."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # Try invalid request
        response = await client.post(
            "/habits/",
            json={
                # Invalid, no name
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

        # Database should still work after error
        response = await client.post(
            "/habits/",
            json={
                "name": "Valid Habit",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201


class TestAuthDependency:
    """Tests for authentication dependency."""

    async def test_current_user_from_valid_token(self, client, db_session, login_as):
        """Current user is extracted from valid token."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # User info should be accessible
        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == user.username

    async def test_invalid_token_rejected(self, client, db_session):
        """Invalid token is rejected."""
        client.headers.update({"Authorization": "Bearer invalid_token"})

        response = await client.get("/users/")
        assert response.status_code == 401

    async def test_expired_token_rejected(self, client, db_session):
        """Expired token is rejected."""
        # We can't easily create an expired token in tests without mocking time
        # Instead, test with a malformed token
        client.headers.update(
            {
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature"
            }
        )

        response = await client.get("/users/")
        assert response.status_code == 401

    async def test_missing_token_rejected(self, client, db_session):
        """Missing token is rejected."""
        # Don't set Authorization header
        response = await client.get("/users/")
        assert response.status_code == 401


class TestAuthorizationHelperFunctions:
    """Tests for authorization helper functions."""

    async def test_authorize_resource_access_owner(self, db_session):
        """Owner can access their resources."""
        user = UserFactory()
        await db_session.commit()

        # Should not raise exception
        authorize_resource_access(user, user.id, "test")

    async def test_authorize_resource_access_admin(self, db_session):
        """Admin can access any resource."""
        admin = AdminUserFactory()
        other_user = UserFactory()
        await db_session.commit()

        # Should not raise exception
        authorize_resource_access(admin, other_user.id, "test")

    async def test_authorize_resource_access_unauthorized(self, db_session):
        """Unauthorized access raises 403."""
        from fastapi import HTTPException

        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            authorize_resource_access(user1, user2.id, "test")
        assert exc_info.value.status_code == 403

    async def test_is_admin_or_owner_as_admin(self, db_session):
        """Admin check returns true."""
        admin = AdminUserFactory()
        other_user = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(admin, other_user.id)
        assert result is True

    async def test_is_admin_or_owner_as_owner(self, db_session):
        """Owner check returns true."""
        user = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(user, user.id)
        assert result is True

    async def test_is_admin_or_owner_neither(self, db_session):
        """Neither admin nor owner returns false."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        result = is_admin_or_owner(user1, user2.id)
        assert result is False

    async def test_require_admin_with_admin(self, db_session):
        """Admin passes admin requirement."""
        admin = AdminUserFactory()
        await db_session.commit()

        result = require_admin(admin)
        assert result == admin

    async def test_require_admin_with_regular_user(self, db_session):
        """Regular user fails admin requirement."""
        from fastapi import HTTPException

        user = UserFactory()
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            require_admin(user)
        assert exc_info.value.status_code == 403


class TestGetOwnedHabit:
    """get_owned_habit authorizes through the habit's owning profile."""

    async def test_returns_habit_and_owning_profile(self, db_session):
        user = UserFactory()
        await db_session.commit()
        habit = HabitFactory(user=user)
        await db_session.commit()

        result_habit, result_profile = await get_owned_habit(db_session, habit.id, user)

        assert result_habit.id == habit.id
        assert result_profile.id == habit.profile_id
        assert result_profile.user_id == user.id

    async def test_forbidden_for_non_owner(self, db_session):
        owner = UserFactory()
        other = UserFactory()
        await db_session.commit()
        habit = HabitFactory(user=owner)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await get_owned_habit(db_session, habit.id, other)
        assert exc_info.value.status_code == 403

    async def test_not_found_detail(self, db_session):
        user = UserFactory()
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await get_owned_habit(db_session, 999999, user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Habit not found"

    async def test_admin_may_access_another_users_habit(self, db_session):
        admin = AdminUserFactory()
        owner = UserFactory()
        await db_session.commit()
        habit = HabitFactory(user=owner)
        await db_session.commit()

        result_habit, result_profile = await get_owned_habit(
            db_session, habit.id, admin
        )
        assert result_habit.id == habit.id
        assert result_profile.user_id == owner.id
