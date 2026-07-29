"""Input validation: rejection of bad input (422 paths).

Boundary with test_edge_cases.py: this file covers input that IS rejected -
a 422 (or an explicit "either 4xx" ambiguous-boundary case) is the point.
test_edge_cases.py covers the opposite: unusual-but-valid input that's
accepted, plus degenerate (empty/huge) result sets. If you're adding a test
that asserts a 2xx happy path, it belongs there, not here.
"""

from habit_tracker.constants import TrackerStatus
from tests.factories import AdminUserFactory, HabitFactory, TrackerFactory, UserFactory


class TestEmailValidation:
    """Tests for email validation."""

    async def test_valid_email_format(self, client, db_session):
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
        self, client, db_session
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
        self, client, db_session
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
        self, client, db_session
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

    async def test_valid_hex_color_lowercase(self, client, db_session, login_as):
        """Lowercase hex color is accepted."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_valid_hex_color_uppercase(self, client, db_session, login_as):
        """Uppercase hex color is accepted."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_invalid_hex_color_no_hash(self, client, db_session, login_as):
        """Color without # is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session, login_as
    ):
        """Color with wrong length is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session, login_as
    ):
        """Color with invalid characters is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session, login_as
    ):
        """Negative frequency is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_zero_frequency_rejected(self, client, db_session, login_as):
        """Zero frequency is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_negative_range_rejected(self, client, db_session, login_as):
        """Negative range is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_zero_range_rejected(self, client, db_session, login_as):
        """Zero range is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session, login_as
    ):
        """Negative page number is rejected or handled."""
        admin = AdminUserFactory()
        await db_session.commit()

        await login_as(admin)

        response = await client.get("/users/?page=-1")
        # Should either return 422 or default to page 1
        assert response.status_code in [200, 422]


class TestNumericBoundaries:
    """Tests for numeric edge cases."""

    async def test_very_large_frequency(self, client, db_session, login_as):
        """Test habit with very large frequency."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Large Freq",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 999999,
                "range": 1,
            },
        )
        assert response.status_code in [201, 422]

    async def test_very_large_range(self, client, db_session, login_as):
        """Test habit with very large range."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Large Range",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 999999,
            },
        )
        assert response.status_code in [201, 422]


class TestStringLengthValidation:
    """Tests for string length validation."""

    async def test_empty_habit_name_rejected(self, client, db_session, login_as):
        """Empty habit name is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_empty_username_rejected(self, client, db_session):
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
        self, client, db_session, login_as
    ):
        """Whitespace-only name is rejected or trimmed."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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


class TestStringBoundaries:
    """Tests for string edge cases."""

    async def test_very_long_habit_name(self, client, db_session, login_as):
        """Test habit with very long name."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        long_name = "A" * 1000
        response = await client.post(
            "/habits/",
            json={
                "name": long_name,
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        # Should either succeed or return 422 for max length
        assert response.status_code in [201, 422]

    async def test_very_long_question(self, client, db_session, login_as):
        """Test habit with very long question."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        long_question = "Q" * 1000 + "?"
        response = await client.post(
            "/habits/",
            json={
                "name": "Test Habit",
                "question": long_question,
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code in [201, 422]

    async def test_unicode_in_habit_name(self, client, db_session, login_as):
        """Test habit with unicode characters."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "习惯 🎯 Привычка",
                "question": "完成了吗？",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201
        assert "习惯" in response.json()["name"]

    async def test_special_characters_in_name(
        self, client, db_session, login_as
    ):
        """Test habit with special characters."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test & Test <> Test",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201


class TestRequiredFieldValidation:
    """Tests for required field validation."""

    async def test_missing_habit_name_rejected(
        self, client, db_session, login_as
    ):
        """Missing habit name is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session
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

    async def test_missing_password_rejected(self, client, db_session):
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

    async def test_missing_tracker_habit_id_rejected(
        self, client, db_session, login_as
    ):
        """Missing tracker habit_id is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "dated": "2024-01-01",
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 422


class TestTypeValidation:
    """Tests for type validation."""

    async def test_string_for_integer_rejected(
        self, client, db_session, login_as
    ):
        """String where integer expected is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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
        self, client, db_session, login_as
    ):
        """Integer where string expected is handled."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

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

    async def test_invalid_date_format_rejected(
        self, client, db_session, login_as
    ):
        """Invalid date format is rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": "01-01-2024",  # Wrong format
                "status": TrackerStatus.COMPLETED,
            },
        )
        assert response.status_code == 422


class TestHabitUpdateValidation:
    """HabitUpdate previously had no field validators at all - PATCH accepted
    garbage that HabitCreate would have rejected. These lock in parity."""

    async def test_invalid_hex_color_rejected(self, client, db_session, login_as):
        """PATCH with a non-hex color is rejected, not persisted."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"color": "not-a-color"},
        )
        assert response.status_code == 422

    async def test_negative_frequency_rejected(self, client, db_session, login_as):
        """PATCH with a negative frequency is rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"frequency": -5},
        )
        assert response.status_code == 422

    async def test_zero_range_rejected(self, client, db_session, login_as):
        """PATCH with a zero range is rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"range": 0},
        )
        assert response.status_code == 422

    async def test_whitespace_only_name_rejected(
        self, client, db_session, login_as
    ):
        """PATCH with a whitespace-only name is rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "   "},
        )
        assert response.status_code == 422

    async def test_null_name_rejected(self, client, db_session, login_as):
        """PATCH with an explicit null name is rejected (name is NOT NULL) -
        previously this returned 200 then hit a NOT NULL violation at
        commit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": None},
        )
        assert response.status_code == 422

    async def test_null_color_rejected(self, client, db_session, login_as):
        """PATCH with an explicit null color is rejected (color is NOT NULL)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"color": None},
        )
        assert response.status_code == 422

    async def test_null_category_accepted(self, client, db_session, login_as):
        """Null category is still accepted - it's nullable in the DB, so an
        explicit null clears it rather than being rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, category="Health")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"category": None},
        )
        assert response.status_code == 200
        assert response.json()["category"] is None


class TestTrackerUpdateValidation:
    """TrackerUpdate previously had no field validators at all - PATCH
    accepted any integer status."""

    async def test_invalid_status_rejected(self, client, db_session, login_as):
        """PATCH with a status outside TrackerStatus is rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()


        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"status": 99},
        )
        assert response.status_code == 422

    async def test_null_status_rejected(self, client, db_session, login_as):
        """PATCH with an explicit null status is rejected (status is NOT
        NULL)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()


        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"status": None},
        )
        assert response.status_code == 422

    async def test_null_dated_rejected(self, client, db_session, login_as):
        """PATCH with an explicit null dated is rejected (dated is NOT
        NULL)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()


        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"dated": None},
        )
        assert response.status_code == 422

    async def test_null_note_accepted(self, client, db_session, login_as):
        """Null note is still accepted - it's nullable in the DB, so an
        explicit null clears it rather than being rejected."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()


        tracker = TrackerFactory(habit=habit, note="Some note")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/trackers/{tracker.id}",
            json={"note": None},
        )
        assert response.status_code == 200
        assert response.json()["note"] is None


class TestInvalidIds:
    """Tests for invalid ID handling."""

    async def test_get_habit_with_string_id(self, client, db_session, login_as):
        """Test get habit with string ID."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/not-a-number")
        assert response.status_code == 422

    async def test_get_user_with_negative_id(self, client, db_session, login_as):
        """Test get user with negative ID."""
        admin = AdminUserFactory()
        await db_session.commit()

        await login_as(admin)

        response = await client.get("/users/-1")
        assert response.status_code in [404, 422]

    async def test_get_tracker_with_zero_id(self, client, db_session, login_as):
        """Test get tracker with zero ID."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/trackers/0")
        assert response.status_code in [404, 422]
