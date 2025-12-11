"""Tests for authentication endpoints."""

from sqlalchemy import select

from habit_tracker.core.security import verify_password
from habit_tracker.schemas.db_models import User
from tests.factories import UserFactory


class TestUserRegistration:
    """Tests for /auth/register endpoint."""

    async def test_register_new_user(self, client, db_session):
        """Successfully register a new user with valid data."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "first_name": "John",
                "last_name": "Doe",
                "email": "newuser@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Verify user was created in database
        result = await db_session.execute(
            select(User).filter(User.username == "newuser")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.email == "newuser@example.com"

    async def test_register_duplicate_email(self, client, db_session, setup_factories):
        """Reject registration with existing email (400)."""
        UserFactory(email="existing@example.com")
        await db_session.commit()

        response = await client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "first_name": "John",
                "last_name": "Doe",
                "email": "existing@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 400
        assert "Email already registered" in response.json()["detail"]

    async def test_register_duplicate_username(
        self, client, db_session, setup_factories
    ):
        """Reject registration with existing username (400)."""
        UserFactory(username="existinguser")
        await db_session.commit()

        response = await client.post(
            "/auth/register",
            json={
                "username": "existinguser",
                "first_name": "John",
                "last_name": "Doe",
                "email": "new@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 400
        assert "Username already taken" in response.json()["detail"]

    async def test_register_invalid_email(self, client):
        """Reject registration with invalid email format (422)."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "first_name": "John",
                "last_name": "Doe",
                "email": "not-an-email",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 422

    async def test_register_missing_fields(self, client):
        """Reject registration with missing required fields (422)."""
        # Missing username
        response = await client.post(
            "/auth/register",
            json={
                "first_name": "John",
                "last_name": "Doe",
                "email": "test@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 422

        # Missing email
        response = await client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "first_name": "John",
                "last_name": "Doe",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 422

        # Missing password
        response = await client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "first_name": "John",
                "last_name": "Doe",
                "email": "test@example.com",
            },
        )
        assert response.status_code == 422

    async def test_register_returns_tokens(self, client):
        """Verify registration returns access and refresh tokens."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "tokenuser",
                "first_name": "Token",
                "last_name": "User",
                "email": "tokenuser@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert len(data["access_token"]) > 0
        assert len(data["refresh_token"]) > 0
        # Tokens should be different
        assert data["access_token"] != data["refresh_token"]

    async def test_register_password_hashing(self, client, db_session):
        """Verify password is hashed, not stored in plaintext."""
        plaintext_password = "mysecretpassword123"
        response = await client.post(
            "/auth/register",
            json={
                "username": "hashuser",
                "first_name": "Hash",
                "last_name": "User",
                "email": "hashuser@example.com",
                "plaintext_password": plaintext_password,
            },
        )
        assert response.status_code == 201

        # Verify password is hashed in database
        result = await db_session.execute(
            select(User).filter(User.username == "hashuser")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.password_hash != plaintext_password
        assert verify_password(plaintext_password, user.password_hash)


class TestUserLogin:
    """Tests for /auth/login endpoint."""

    async def test_login_with_username(self, client, db_session, setup_factories):
        """Successfully login with username and password."""
        user = UserFactory()
        await db_session.commit()

        response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_wrong_password(self, client, db_session, setup_factories):
        """Reject login with incorrect password (401)."""
        user = UserFactory(username="wrongpassuser")
        await db_session.commit()

        response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "Incorrect username/email or password" in response.json()["detail"]

    async def test_login_nonexistent_user(self, client):
        """Reject login for non-existent user (401)."""
        response = await client.post(
            "/auth/login",
            data={"username": "nonexistent", "password": "anypassword"},
        )
        assert response.status_code == 401
        assert "Incorrect username/email or password" in response.json()["detail"]

    async def test_login_returns_tokens(self, client, db_session, setup_factories):
        """Verify login returns both access and refresh tokens."""
        user = UserFactory()
        await db_session.commit()

        response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert len(data["access_token"]) > 0
        assert len(data["refresh_token"]) > 0

    async def test_login_token_type(self, client, db_session, setup_factories):
        """Verify token_type is 'bearer'."""
        user = UserFactory()
        await db_session.commit()

        response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"


class TestTokenRefresh:
    """Tests for /auth/refresh endpoint."""

    async def test_refresh_with_valid_token(self, client, db_session, setup_factories):
        """Successfully refresh with valid refresh token."""
        user = UserFactory()
        await db_session.commit()

        # Login to get tokens
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        tokens = login_response.json()

        # Refresh token
        response = await client.post(
            "/auth/refresh",
            params={"refresh_token": tokens["refresh_token"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_with_access_token(self, client, db_session, setup_factories):
        """Reject refresh attempt with access token (401)."""
        user = UserFactory()
        await db_session.commit()

        # Login to get tokens
        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        tokens = login_response.json()

        # Try to refresh with access token instead of refresh token
        response = await client.post(
            "/auth/refresh",
            params={"refresh_token": tokens["access_token"]},
        )
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]

    async def test_refresh_with_expired_token(
        self, client, db_session, setup_factories
    ):
        """Reject refresh with expired token (401)."""
        # Create an expired token manually
        from datetime import datetime, timedelta, timezone

        import jwt

        from habit_tracker.core.config import settings

        user = UserFactory()
        await db_session.commit()

        # Create an expired refresh token
        expired_token = jwt.encode(
            {
                "sub": str(user.id),
                "type": "refresh",
                "exp": datetime.now(timezone.utc) - timedelta(days=1),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        response = await client.post(
            "/auth/refresh",
            params={"refresh_token": expired_token},
        )
        assert response.status_code == 401

    async def test_refresh_with_invalid_token(self, client):
        """Reject refresh with malformed token (401)."""
        response = await client.post(
            "/auth/refresh",
            params={"refresh_token": "invalid.malformed.token"},
        )
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]
