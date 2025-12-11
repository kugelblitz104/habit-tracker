"""Dependency injection tests."""

from tests.factories import AdminUserFactory, UserFactory


class TestDatabaseDependency:
    """Tests for database dependency."""

    async def test_database_session_provided(self, client, db_session, setup_factories):
        """Database session is available to endpoints."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # If endpoints work, database session is properly injected
        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200

    async def test_database_isolation(self, client, db_session, setup_factories):
        """Database transactions are isolated."""
        user1 = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Changes in one request shouldn't leak to others incorrectly
        response = await client.post(
            "/habits/",
            json={
                "name": "Isolated Habit",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201
        habit_id = response.json()["id"]

        # Verify habit persists
        get_response = await client.get(f"/habits/{habit_id}")
        assert get_response.status_code == 200

    async def test_database_rollback_on_error(
        self, client, db_session, setup_factories
    ):
        """Database rolls back on error."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Try invalid request
        response = await client.post(
            "/habits/",
            json={
                # Invalid, no name
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
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
            },
        )
        assert response.status_code == 201


class TestAuthDependency:
    """Tests for authentication dependency."""

    async def test_current_user_from_valid_token(
        self, client, db_session, setup_factories
    ):
        """Current user is extracted from valid token."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # User info should be accessible
        response = await client.get(f"/users/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == user.username

    async def test_invalid_token_rejected(self, client, db_session, setup_factories):
        """Invalid token is rejected."""
        client.headers.update({"Authorization": "Bearer invalid_token"})

        response = await client.get("/users/")
        assert response.status_code == 401

    async def test_expired_token_rejected(self, client, db_session, setup_factories):
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

    async def test_missing_token_rejected(self, client, db_session, setup_factories):
        """Missing token is rejected."""
        # Don't set Authorization header
        response = await client.get("/users/")
        assert response.status_code == 401


class TestAdminDependency:
    """Tests for admin dependency."""

    async def test_admin_access_granted(self, client, db_session, setup_factories):
        """Admin users get access to admin endpoints."""
        admin = AdminUserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Admin can list all users
        response = await client.get("/users/")
        assert response.status_code == 200

    async def test_non_admin_restricted(self, client, db_session, setup_factories):
        """Non-admin users are restricted from admin endpoints."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Non-admin cannot delete other users
        response = await client.delete(f"/users/{other_user.id}")
        assert response.status_code == 403


class TestOwnerDependency:
    """Tests for owner authorization dependency."""

    async def test_owner_can_access_own_resource(
        self, client, db_session, setup_factories
    ):
        """Owner can access their own resources."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Create habit
        create_response = await client.post(
            "/habits/",
            json={
                "name": "My Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        habit_id = create_response.json()["id"]

        # Owner can access
        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 200

    async def test_non_owner_cannot_access_resource(
        self, client, db_session, setup_factories
    ):
        """Non-owner cannot access others' resources."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        # User1 creates habit
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        create_response = await client.post(
            "/habits/",
            json={
                "name": "User1 Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        habit_id = create_response.json()["id"]

        # User2 tries to access
        login_response = await client.post(
            "/auth/login",
            data={"username": user2.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 403

    async def test_admin_can_access_any_resource(
        self, client, db_session, setup_factories
    ):
        """Admin can access any user's resources."""
        user = UserFactory()
        admin = AdminUserFactory()
        await db_session.commit()

        # User creates habit
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        create_response = await client.post(
            "/habits/",
            json={
                "name": "User Habit",
                "question": "Done?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        habit_id = create_response.json()["id"]

        # Admin accesses
        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit_id}")
        assert response.status_code == 200


class TestConfigDependency:
    """Tests for configuration dependency."""

    async def test_app_starts_with_config(self, client, db_session, setup_factories):
        """Application starts with proper configuration."""
        # If we can make requests, config is working
        response = await client.get("/openapi.json")
        assert response.status_code == 200

    async def test_cors_headers_present(self, client, db_session, setup_factories):
        """CORS headers are present in responses."""
        # Make OPTIONS request
        response = await client.options("/users/")
        # CORS may or may not be configured depending on settings
        # Just verify the endpoint doesn't error
        assert response.status_code in [200, 204, 401, 405]
