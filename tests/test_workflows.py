"""Integration and workflow tests using shared database sessions."""

from datetime import date, timedelta


from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestUserOnboardingFlow:
    """Tests for user onboarding workflows."""

    async def test_complete_user_registration_flow(
        self, shared_client, shared_db_session, setup_factories
    ):
        """Register, login, verify tokens."""
        # Register new user
        register_response = await shared_client.post(
            "/auth/register",
            json={
                "username": "flow_user",
                "first_name": "Flow",
                "last_name": "User",
                "email": "flow@example.com",
                "plaintext_password": "securepassword123",
            },
        )
        assert register_response.status_code == 201
        tokens = register_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Login with credentials
        login_response = await shared_client.post(
            "/auth/login",
            data={"username": "flow_user", "password": "securepassword123"},
        )
        assert login_response.status_code == 200
        login_tokens = login_response.json()
        assert "access_token" in login_tokens

        # Verify token works
        shared_client.headers.update(
            {"Authorization": f"Bearer {login_tokens['access_token']}"}
        )
        response = await shared_client.get("/users/")
        assert response.status_code == 200

    async def test_user_creates_first_habit(
        self, shared_client, shared_db_session, setup_factories
    ):
        """New user creates their first habit."""
        # Register and login
        await shared_client.post(
            "/auth/register",
            json={
                "username": "habit_user",
                "first_name": "Habit",
                "last_name": "User",
                "email": "habit@example.com",
                "plaintext_password": "password123",
            },
        )
        login_response = await shared_client.post(
            "/auth/login",
            data={"username": "habit_user", "password": "password123"},
        )
        token = login_response.json()["access_token"]
        shared_client.headers.update({"Authorization": f"Bearer {token}"})

        # Create first habit
        habit_response = await shared_client.post(
            "/habits/",
            json={
                "name": "My First Habit",
                "question": "Did I do it?",
                "color": "#00FF00",
                "frequency": 1,
                "range": 1,
            },
        )
        assert habit_response.status_code == 201
        habit = habit_response.json()
        assert habit["name"] == "My First Habit"

    async def test_user_completes_onboarding(self, shared_client, shared_db_session):
        """Full onboarding from registration to first tracker."""

        # Register
        await shared_client.post(
            "/auth/register",
            json={
                "username": "onboard_user",
                "first_name": "Onboard",
                "last_name": "User",
                "email": "onboard@example.com",
                "plaintext_password": "password123",
            },
        )

        # Login
        login_response = await shared_client.post(
            "/auth/login",
            data={"username": "onboard_user", "password": "password123"},
        )
        token = login_response.json()["access_token"]
        shared_client.headers.update({"Authorization": f"Bearer {token}"})

        # Create habit
        habit_response = await shared_client.post(
            "/habits/",
            json={
                "name": "Onboarding Habit",
                "question": "Complete?",
                "color": "#FF0000",
                "frequency": 1,
                "range": 1,
            },
        )
        habit_id = habit_response.json()["id"]

        # Create first tracker
        tracker_response = await shared_client.post(
            "/trackers/",
            json={
                "habit_id": habit_id,
                "dated": date.today().isoformat(),
                "completed": True,
            },
        )
        assert tracker_response.status_code == 201


class TestHabitTrackingFlow:
    """Tests for habit tracking workflows."""

    async def test_daily_habit_completion_flow(
        self, client, db_session, setup_factories
    ):
        """Create habit, mark complete, verify KPIs."""
        user = UserFactory()
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Create habit
        habit_response = await client.post(
            "/habits/",
            json={
                "name": "Daily Habit",
                "question": "Done?",
                "color": "#0000FF",
                "frequency": 1,
                "range": 1,
            },
        )
        habit_id = habit_response.json()["id"]

        # Mark complete
        await client.post(
            "/trackers/",
            json={
                "habit_id": habit_id,
                "dated": date.today().isoformat(),
                "completed": True,
            },
        )

        # Check KPIs
        kpi_response = await client.get(f"/habits/{habit_id}/kpis")
        assert kpi_response.status_code == 200
        kpis = kpi_response.json()
        assert kpis["total_completions"] == 1

    async def test_habit_skip_flow(self, client, db_session, setup_factories):
        """Skip habit and verify it doesn't break streak."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Complete yesterday
        await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": (date.today() - timedelta(days=1)).isoformat(),
                "completed": True,
            },
        )

        # Skip today
        await client.post(
            "/trackers/",
            json={
                "habit_id": habit.id,
                "dated": date.today().isoformat(),
                "completed": False,
                "skipped": True,
            },
        )

        # Check habit status
        habit_response = await client.get(f"/habits/{habit.id}")
        assert habit_response.status_code == 200
        data = habit_response.json()
        assert data["skipped_today"] is True

    async def test_habit_archive_unarchive_flow(
        self, client, db_session, setup_factories
    ):
        """Archive and unarchive habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, archived=False)
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Archive
        archive_response = await client.patch(
            f"/habits/{habit.id}",
            json={"archived": True},
        )
        assert archive_response.status_code == 200
        assert archive_response.json()["archived"] is True

        # Unarchive
        unarchive_response = await client.patch(
            f"/habits/{habit.id}",
            json={"archived": False},
        )
        assert unarchive_response.status_code == 200
        assert unarchive_response.json()["archived"] is False


class TestStreakBuildingFlow:
    """Tests for streak building workflows."""

    async def test_build_streak_consecutive_days(
        self, client, db_session, setup_factories
    ):
        """Build streak over consecutive days."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        # Create trackers for 5 consecutive days
        for i in range(5):
            TrackerFactory(
                habit=habit,
                dated=date.today() - timedelta(days=i),
                completed=True,
            )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # Check streaks
        streaks_response = await client.get(f"/habits/{habit.id}/streaks")
        assert streaks_response.status_code == 200
        streaks = streaks_response.json()
        assert len(streaks) >= 1

    async def test_build_streak_with_frequency(
        self, client, db_session, setup_factories
    ):
        """Build streak with frequency > 1."""
        user = UserFactory()
        await db_session.commit()

        # 3 times per week habit
        habit = HabitFactory(user=user, frequency=3, range=7)
        await db_session.commit()

        # Complete 3 times in first week
        TrackerFactory(habit=habit, dated=date.today(), completed=True)
        TrackerFactory(
            habit=habit, dated=date.today() - timedelta(days=2), completed=True
        )
        TrackerFactory(
            habit=habit, dated=date.today() - timedelta(days=4), completed=True
        )
        await db_session.commit()

        login_response = await client.post(
            "/auth/login",
            data={"username": user.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        kpis_response = await client.get(f"/habits/{habit.id}/kpis")
        assert kpis_response.status_code == 200
        kpis = kpis_response.json()
        assert kpis["total_completions"] == 3


class TestMultiUserScenarios:
    """Tests for multi-user scenarios."""

    async def test_multiple_users_isolated_data(
        self, client, db_session, setup_factories
    ):
        """Verify user data isolation."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user1, name="User1 Habit")
        habit2 = HabitFactory(user=user2, name="User2 Habit")
        await db_session.commit()

        # Login as user1
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # User1 can access their habit
        response = await client.get(f"/habits/{habit1.id}")
        assert response.status_code == 200

        # User1 cannot access user2's habit
        response = await client.get(f"/habits/{habit2.id}")
        assert response.status_code == 403

    async def test_admin_manages_multiple_users(
        self, client, db_session, setup_factories
    ):
        """Admin can manage multiple users."""
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

        # Admin can see all users
        response = await client.get("/users/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3  # admin + 2 users

        # Admin can modify user1
        response = await client.patch(
            f"/users/{user1.id}",
            json={"first_name": "Modified1"},
        )
        assert response.status_code == 200

        # Admin can modify user2
        response = await client.patch(
            f"/users/{user2.id}",
            json={"first_name": "Modified2"},
        )
        assert response.status_code == 200

    async def test_concurrent_habit_tracking(self, client, db_session, setup_factories):
        """Multiple users track habits simultaneously."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user1)
        habit2 = HabitFactory(user=user2)
        await db_session.commit()

        # Both users create trackers for today
        TrackerFactory(habit=habit1, dated=date.today(), completed=True)
        TrackerFactory(habit=habit2, dated=date.today(), completed=True)
        await db_session.commit()

        # Verify user1's tracker
        login_response = await client.post(
            "/auth/login",
            data={"username": user1.username, "password": "password123"},
        )
        token = login_response.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        response = await client.get(f"/habits/{habit1.id}")
        assert response.status_code == 200
        assert response.json()["completed_today"] is True
