"""Edge cases and boundary tests."""

from datetime import date, timedelta

from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestStringBoundaries:
    """Tests for string edge cases."""

    async def test_very_long_habit_name(self, client, db_session, setup_factories):
        """Test habit with very long name."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_very_long_question(self, client, db_session, setup_factories):
        """Test habit with very long question."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

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

    async def test_unicode_in_habit_name(self, client, db_session, setup_factories):
        """Test habit with unicode characters."""
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
        self, client, db_session, setup_factories
    ):
        """Test habit with special characters."""
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
                "name": "Test & Test <> Test",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 201


class TestDateEdgeCases:
    """Tests for date edge cases."""

    async def test_tracker_far_future_date(self, client, db_session, setup_factories):
        """Test tracker with far future date."""
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

        future_date = (date.today() + timedelta(days=365 * 10)).isoformat()
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": future_date,
                "completed": True,
            },
        )
        # May allow or reject future dates
        assert response.status_code in [201, 400, 422]

    async def test_tracker_far_past_date(self, client, db_session, setup_factories):
        """Test tracker with far past date."""
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

        past_date = (date.today() - timedelta(days=365 * 10)).isoformat()
        response = await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": past_date,
                "completed": True,
            },
        )
        assert response.status_code in [201, 400, 422]

    async def test_leap_year_date(self, client, db_session, setup_factories):
        """Test tracker with leap year date."""
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
                "dated": "2024-02-29",  # Leap year
                "completed": True,
            },
        )
        assert response.status_code == 201


class TestNumericBoundaries:
    """Tests for numeric edge cases."""

    async def test_very_large_frequency(self, client, db_session, setup_factories):
        """Test habit with very large frequency."""
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
                "name": "Large Freq",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 999999,
                "range": 1,
            },
        )
        assert response.status_code in [201, 422]

    async def test_very_large_range(self, client, db_session, setup_factories):
        """Test habit with very large range."""
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
                "name": "Large Range",
                "question": "Test?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 999999,
            },
        )
        assert response.status_code in [201, 422]


class TestManyRecords:
    """Tests for handling many records."""

    async def test_user_with_many_habits(self, client, db_session, setup_factories):
        """Test user with many habits."""
        user = UserFactory()
        await db_session.commit()

        for i in range(100):
            HabitFactory(user=user, name=f"Habit {i}")
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200

    async def test_habit_with_many_trackers(self, client, db_session, setup_factories):
        """Test habit with many trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(100):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit.id}/trackers")
        assert response.status_code == 200


class TestEmptyResults:
    """Tests for empty result handling."""

    async def test_user_with_no_habits(self, client, db_session, setup_factories):
        """Test user with no habits."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/users/{user.id}/habits")
        assert response.status_code == 200
        data = response.json()
        assert data["habits"] == []

    async def test_habit_with_no_trackers(self, client, db_session, setup_factories):
        """Test habit with no trackers."""
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
        assert data["trackers"] == []

    async def test_habit_kpis_with_no_data(self, client, db_session, setup_factories):
        """Test KPIs with no completion data."""
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
        kpis = response.json()
        assert kpis["total_completions"] == 0


class TestInvalidIds:
    """Tests for invalid ID handling."""

    async def test_get_habit_with_string_id(self, client, db_session, setup_factories):
        """Test get habit with string ID."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/habits/not-a-number")
        assert response.status_code == 422

    async def test_get_user_with_negative_id(self, client, db_session, setup_factories):
        """Test get user with negative ID."""
        admin = AdminUserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": admin.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/users/-1")
        assert response.status_code in [404, 422]

    async def test_get_tracker_with_zero_id(self, client, db_session, setup_factories):
        """Test get tracker with zero ID."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get("/trackers/0")
        assert response.status_code in [404, 422]
