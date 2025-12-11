"""Tests for security functions."""

from datetime import datetime, timedelta, timezone

import jwt

from habit_tracker.core.config import settings
from habit_tracker.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_password_hashing(self):
        """Verify password hashing produces different hashes."""
        password = "mypassword123"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Same password should produce different hashes (due to salt)
        assert hash1 != hash2
        # Both should be valid for the same password
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)

    def test_password_verification(self):
        """Verify correct password validates successfully."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_password_verification_fails(self):
        """Verify incorrect password fails validation."""
        password = "correctpassword"
        wrong_password = "wrongpassword"
        hashed = get_password_hash(password)

        assert verify_password(wrong_password, hashed) is False

    def test_password_hash_different_from_plaintext(self):
        """Verify hash is different from plaintext password."""
        password = "plaintext"
        hashed = get_password_hash(password)

        assert hashed != password
        assert len(hashed) > len(password)

    def test_empty_password_hashing(self):
        """Test hashing empty password."""
        password = ""
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True
        assert verify_password("notempty", hashed) is False


class TestAccessTokenCreation:
    """Tests for access token creation."""

    def test_access_token_creation(self):
        """Verify access token creation and structure."""
        user_id = 123
        token = create_access_token(data={"sub": str(user_id)})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify structure
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_access_token_contains_user_id(self):
        """Verify token payload contains user ID."""
        user_id = 456
        token = create_access_token(data={"sub": str(user_id)})

        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)

    def test_access_token_custom_expiry(self):
        """Test access token with custom expiry time."""
        user_id = 789
        custom_expiry = timedelta(minutes=5)
        token = create_access_token(
            data={"sub": str(user_id)}, expires_delta=custom_expiry
        )

        payload = decode_token(token)
        assert payload is not None
        # Token should be valid (not expired)
        assert payload["sub"] == str(user_id)


class TestRefreshTokenCreation:
    """Tests for refresh token creation."""

    def test_refresh_token_creation(self):
        """Verify refresh token creation and structure."""
        user_id = 123
        token = create_refresh_token(data={"sub": str(user_id)})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify structure
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
        assert "exp" in payload

    def test_refresh_token_different_from_access(self):
        """Verify refresh token is different from access token."""
        user_id = 123
        access_token = create_access_token(data={"sub": str(user_id)})
        refresh_token = create_refresh_token(data={"sub": str(user_id)})

        assert access_token != refresh_token


class TestTokenDecoding:
    """Tests for token decoding."""

    def test_token_decode_valid(self):
        """Verify valid token decodes correctly."""
        user_id = 123
        token = create_access_token(data={"sub": str(user_id)})

        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"

    def test_token_decode_expired(self):
        """Verify expired token returns None."""
        user_id = 123
        # Create token that expired 1 hour ago
        expired_token = jwt.encode(
            {
                "sub": str(user_id),
                "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        payload = decode_token(expired_token)
        assert payload is None

    def test_token_decode_invalid(self):
        """Verify invalid token returns None."""
        invalid_tokens = [
            "invalid.token.string",
            "notavalidtoken",
            "",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
        ]

        for invalid_token in invalid_tokens:
            payload = decode_token(invalid_token)
            assert payload is None

    def test_token_decode_wrong_secret(self):
        """Verify token with wrong secret returns None."""
        user_id = 123
        # Create token with different secret
        wrong_secret_token = jwt.encode(
            {
                "sub": str(user_id),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "wrong_secret_key",
            algorithm=settings.algorithm,
        )

        payload = decode_token(wrong_secret_token)
        assert payload is None


class TestTokenExpiry:
    """Tests for token expiry times."""

    def test_token_expiry_times(self):
        """Verify tokens have correct expiry times."""
        user_id = 123
        before_creation = datetime.now(timezone.utc)

        access_token = create_access_token(data={"sub": str(user_id)})
        refresh_token = create_refresh_token(data={"sub": str(user_id)})

        after_creation = datetime.now(timezone.utc)

        # Decode tokens
        access_payload = jwt.decode(
            access_token, settings.secret_key, algorithms=[settings.algorithm]
        )
        refresh_payload = jwt.decode(
            refresh_token, settings.secret_key, algorithms=[settings.algorithm]
        )

        # Access token expiry should be around access_token_expiry_minutes from now
        # Add 1 second tolerance for test execution time
        access_exp = datetime.fromtimestamp(access_payload["exp"], tz=timezone.utc)
        expected_access_exp_min = (
            before_creation
            + timedelta(minutes=settings.access_token_expiry_minutes)
            - timedelta(seconds=1)
        )
        expected_access_exp_max = (
            after_creation
            + timedelta(minutes=settings.access_token_expiry_minutes)
            + timedelta(seconds=1)
        )
        assert expected_access_exp_min <= access_exp <= expected_access_exp_max

        # Refresh token expiry should be around refresh_token_expiry_days from now
        # Add 1 second tolerance for test execution time
        refresh_exp = datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc)
        expected_refresh_exp_min = (
            before_creation
            + timedelta(days=settings.refresh_token_expiry_days)
            - timedelta(seconds=1)
        )
        expected_refresh_exp_max = (
            after_creation
            + timedelta(days=settings.refresh_token_expiry_days)
            + timedelta(seconds=1)
        )
        assert expected_refresh_exp_min <= refresh_exp <= expected_refresh_exp_max

    def test_access_token_expires_before_refresh(self):
        """Verify access token expires before refresh token."""
        user_id = 123
        access_token = create_access_token(data={"sub": str(user_id)})
        refresh_token = create_refresh_token(data={"sub": str(user_id)})

        access_payload = jwt.decode(
            access_token, settings.secret_key, algorithms=[settings.algorithm]
        )
        refresh_payload = jwt.decode(
            refresh_token, settings.secret_key, algorithms=[settings.algorithm]
        )

        assert access_payload["exp"] < refresh_payload["exp"]


class TestTokenTypes:
    """Tests for token type verification."""

    def test_access_token_type(self):
        """Verify access token has correct type."""
        token = create_access_token(data={"sub": "123"})
        payload = decode_token(token)

        assert payload is not None
        assert payload["type"] == "access"

    def test_refresh_token_type(self):
        """Verify refresh token has correct type."""
        token = create_refresh_token(data={"sub": "123"})
        payload = decode_token(token)

        assert payload is not None
        assert payload["type"] == "refresh"

    def test_token_types_are_different(self):
        """Verify access and refresh tokens have different types."""
        access_token = create_access_token(data={"sub": "123"})
        refresh_token = create_refresh_token(data={"sub": "123"})

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        assert access_payload is not None
        assert refresh_payload is not None
        assert access_payload["type"] != refresh_payload["type"]
        assert access_payload["type"] != refresh_payload["type"]
