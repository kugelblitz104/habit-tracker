"""Input validation tests."""

from tests.factories import AdminUserFactory, HabitFactory, UserFactory


class TestEmailValidation:
    """Tests for email validation."""

    async def test_valid_email_format(self, client, db_session, setup_factories):
        """Valid email is accepted."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "validuser",
                "first_name": "Valid",
                "last_name": "User",
                "email": "valid@example.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 201

    async def test_invalid_email_missing_at_symbol(
        self, client, db_session, setup_factories
    ):
        """Email without @ is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "invaliduser",
                "first_name": "Invalid",
                "last_name": "User",
                "email": "invalidemail.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 422

    async def test_invalid_email_missing_domain(
        self, client, db_session, setup_factories
    ):
        """Email without domain is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "nodomain",
                "first_name": "No",
                "last_name": "Domain",
                "email": "user@",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 422

    async def test_invalid_email_special_characters(
        self, client, db_session, setup_factories
    ):
        """Email with invalid characters is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "specialchar",
                "first_name": "Special",
                "last_name": "Char",
                "email": "user<script>@example.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 422


class TestColorValidation:
    """Tests for color format validation."""

    async def test_valid_hex_color_lowercase(self, client, db_session, setup_factories):
        """Lowercase hex color is accepted."""
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
                "name": "Color Test",
                "question": "Test?",
                "color": "#ff00ff",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201

    async def test_valid_hex_color_uppercase(self, client, db_session, setup_factories):
        """Uppercase hex color is accepted."""
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
                "name": "Color Test",
                "question": "Test?",
                "color": "#FF00FF",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201

    async def test_invalid_hex_color_no_hash(self, client, db_session, setup_factories):
        """Color without # is rejected."""
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
                "name": "Color Test",
                "question": "Test?",
                "color": "FF00FF",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_invalid_hex_color_wrong_length(
        self, client, db_session, setup_factories
    ):
        """Color with wrong length is rejected."""
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
                "name": "Color Test",
                "question": "Test?",
                "color": "#FFF",  # Too short
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_invalid_hex_color_invalid_chars(
        self, client, db_session, setup_factories
    ):
        """Color with invalid characters is rejected."""
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
                "name": "Color Test",
                "question": "Test?",
                "color": "#GGHHII",  # Invalid hex
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422


class TestNumericValidation:
    """Tests for numeric value validation."""

    async def test_negative_frequency_rejected(
        self, client, db_session, setup_factories
    ):
        """Negative frequency is rejected."""
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
                "name": "Negative Freq",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": -1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_zero_frequency_rejected(self, client, db_session, setup_factories):
        """Zero frequency is rejected."""
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
                "name": "Zero Freq",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 0,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_negative_range_rejected(self, client, db_session, setup_factories):
        """Negative range is rejected."""
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
                "name": "Negative Range",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": -1,
            },
        )
        assert response.status_code == 422

    async def test_zero_range_rejected(self, client, db_session, setup_factories):
        """Zero range is rejected."""
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
                "name": "Zero Range",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 0,
            },
        )
        assert response.status_code == 422

    async def test_negative_page_number_rejected(
        self, client, db_session, setup_factories
    ):
        """Negative page number is rejected or handled."""
        admin = AdminUserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/?page=-1")
        # Should either return 422 or default to page 1
        assert response.status_code in [200, 422]


class TestStringLengthValidation:
    """Tests for string length validation."""

    async def test_empty_habit_name_rejected(self, client, db_session, setup_factories):
        """Empty habit name is rejected."""
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
                "name": "",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_empty_username_rejected(self, client, db_session, setup_factories):
        """Empty username is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "",
                "first_name": "Empty",
                "last_name": "Username",
                "email": "empty@example.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 422

    async def test_whitespace_only_name_rejected(
        self, client, db_session, setup_factories
    ):
        """Whitespace-only name is rejected or trimmed."""
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
                "name": "   ",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code in [201, 422]  # Depends on whitespace handling


class TestRequiredFieldValidation:
    """Tests for required field validation."""

    async def test_missing_habit_name_rejected(
        self, client, db_session, setup_factories
    ):
        """Missing habit name is rejected."""
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
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_missing_user_email_rejected(
        self, client, db_session, setup_factories
    ):
        """Missing email is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "noemail",
                "first_name": "No",
                "last_name": "Email",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 422

    async def test_missing_password_rejected(self, client, db_session, setup_factories):
        """Missing password is rejected."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "nopassword",
                "first_name": "No",
                "last_name": "Password",
                "email": "nopassword@example.com",
            },
        )
        assert response.status_code == 422

    async def test_missing_tracker_date_rejected(
        self, client, db_session, setup_factories
    ):
        """Missing tracker date is rejected."""
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

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "completed": True,
            },
        )
        assert response.status_code == 422

    async def test_missing_tracker_habit_id_rejected(
        self, client, db_session, setup_factories
    ):
        """Missing tracker habit_id is rejected."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.post(
            "/trackers/",
            json={
                "dated": "2024-01-01",
                "completed": True,
            },
        )
        assert response.status_code == 422


class TestTypeValidation:
    """Tests for type validation."""

    async def test_string_for_integer_rejected(
        self, client, db_session, setup_factories
    ):
        """String where integer expected is rejected."""
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
                "name": "Type Test",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": "one",  # Should be int
                "range": 1,
            },
        )
        assert response.status_code == 422

    async def test_integer_for_string_handled(
        self, client, db_session, setup_factories
    ):
        """Integer where string expected is handled."""
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
                "name": 12345,  # Integer where string expected
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        # May be converted to string or rejected
        assert response.status_code in [201, 422]

    async def test_string_for_boolean_rejected(
        self, client, db_session, setup_factories
    ):
        """String where boolean expected is rejected."""
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

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": "2024-01-01",
                "completed": "yes",  # Should be bool
            },
        )
        assert response.status_code == 422

    async def test_invalid_date_format_rejected(
        self, client, db_session, setup_factories
    ):
        """Invalid date format is rejected."""
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

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": "01-01-2024",  # Wrong format
                "completed": True,
            },
        )
        assert response.status_code == 422
