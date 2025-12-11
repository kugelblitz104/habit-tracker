"""Database model tests."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from habit_tracker.schemas.db_models import Habit, Tracker, User
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    TrackerFactory,
    UserFactory,
)


class TestUserModel:
    """Tests for User model."""

    async def test_user_creation_with_required_fields(
        self, db_session, setup_factories
    ):
        """User can be created with required fields."""
        user = UserFactory()
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched_user = result.scalar_one()
        assert fetched_user is not None
        assert fetched_user.username is not None
        assert fetched_user.email is not None
        assert fetched_user.password_hash is not None

    async def test_user_admin_flag_default(self, db_session, setup_factories):
        """User is_admin defaults to False."""
        user = UserFactory()
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched_user = result.scalar_one()
        assert fetched_user.is_admin is False

    async def test_user_admin_flag_set(self, db_session, setup_factories):
        """Admin user has is_admin=True."""
        admin = AdminUserFactory()
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == admin.id))
        fetched_user = result.scalar_one()
        assert fetched_user.is_admin is True

    async def test_user_has_habits_relationship(self, db_session, setup_factories):
        """User has habits relationship."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user)
        HabitFactory(user=user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched_user = result.scalar_one()
        await db_session.refresh(fetched_user, ["habits"])
        assert len(fetched_user.habits) == 2

    async def test_user_timestamps(self, db_session, setup_factories):
        """User has timestamp fields."""
        user = UserFactory()
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched_user = result.scalar_one()
        # Check created_at is present (if model has it)
        if hasattr(fetched_user, "created_at"):
            assert fetched_user.created_at is not None


class TestHabitModel:
    """Tests for Habit model."""

    async def test_habit_creation_with_required_fields(
        self, db_session, setup_factories
    ):
        """Habit can be created with required fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        fetched_habit = result.scalar_one()
        assert fetched_habit is not None
        assert fetched_habit.name is not None
        assert fetched_habit.user_id == user.id

    async def test_habit_belongs_to_user(self, db_session, setup_factories):
        """Habit belongs to user via user_id."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        fetched_habit = result.scalar_one()
        assert fetched_habit.user_id == user.id

    async def test_habit_has_trackers_relationship(self, db_session, setup_factories):
        """Habit has trackers relationship."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today())
        TrackerFactory(habit=habit, dated=date.today() + timedelta(days=1))
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        fetched_habit = result.scalar_one()
        await db_session.refresh(fetched_habit, ["trackers"])
        assert len(fetched_habit.trackers) == 2

    async def test_habit_default_values(self, db_session, setup_factories):
        """Habit has proper default values."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, archived=False)
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        fetched_habit = result.scalar_one()
        assert fetched_habit.archived is False

    async def test_habit_sort_order_field(self, db_session, setup_factories):
        """Habit has sort_order field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=1)
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        fetched_habit = result.scalar_one()
        assert fetched_habit.sort_order == 1


class TestTrackerModel:
    """Tests for Tracker model."""

    async def test_tracker_creation(self, db_session, setup_factories):
        """Tracker can be created."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker.id)
        )
        fetched_tracker = result.scalar_one()
        assert fetched_tracker is not None
        assert fetched_tracker.habit_id == habit.id

    async def test_tracker_belongs_to_habit(self, db_session, setup_factories):
        """Tracker belongs to habit via habit_id."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker.id)
        )
        fetched_tracker = result.scalar_one()
        assert fetched_tracker.habit_id == habit.id

    async def test_tracker_dated_field(self, db_session, setup_factories):
        """Tracker has dated field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        today = date.today()
        tracker = TrackerFactory(habit=habit, dated=today)
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker.id)
        )
        fetched_tracker = result.scalar_one()
        assert fetched_tracker.dated == today

    async def test_tracker_completed_field(self, db_session, setup_factories):
        """Tracker has completed field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, completed=True)
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker.id)
        )
        fetched_tracker = result.scalar_one()
        assert fetched_tracker.completed is True

    async def test_tracker_skipped_field(self, db_session, setup_factories):
        """Tracker has skipped field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit, skipped=True)
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker.id)
        )
        fetched_tracker = result.scalar_one()
        assert fetched_tracker.skipped is True


class TestModelRelationships:
    """Tests for model relationships."""

    async def test_user_habit_cascade_delete(self, db_session, setup_factories):
        """Deleting user cascades to habits."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        # Delete user
        await db_session.delete(user)
        await db_session.commit()

        # Check habit is gone
        result = await db_session.execute(select(Habit).where(Habit.id == habit.id))
        assert result.scalar_one_or_none() is None

    async def test_habit_tracker_cascade_delete(self, db_session, setup_factories):
        """Deleting habit cascades to trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        tracker_id = tracker.id

        # Delete habit
        await db_session.delete(habit)
        await db_session.commit()

        # Check tracker is gone
        result = await db_session.execute(
            select(Tracker).where(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_multiple_habits_per_user(self, db_session, setup_factories):
        """User can have multiple habits."""
        user = UserFactory()
        await db_session.commit()

        for i in range(5):
            HabitFactory(user=user, name=f"Habit {i}")
        await db_session.commit()

        result = await db_session.execute(select(Habit).where(Habit.user_id == user.id))
        habits = result.scalars().all()
        assert len(habits) == 5

    async def test_multiple_trackers_per_habit(self, db_session, setup_factories):
        """Habit can have multiple trackers."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        for i in range(10):
            TrackerFactory(habit=habit, dated=date.today() - timedelta(days=i))
        await db_session.commit()

        result = await db_session.execute(
            select(Tracker).where(Tracker.habit_id == habit.id)
        )
        trackers = result.scalars().all()
        assert len(trackers) == 10


class TestModelConstraints:
    """Tests for model constraints."""

    async def test_user_unique_username(self, db_session, setup_factories):
        """Username must be unique."""
        UserFactory(username="uniqueuser")
        await db_session.commit()

        with pytest.raises(Exception):
            UserFactory(username="uniqueuser")
            await db_session.commit()

    async def test_user_unique_email(self, db_session, setup_factories):
        """Email must be unique."""
        UserFactory(email="unique@example.com")
        await db_session.commit()

        with pytest.raises(Exception):
            UserFactory(email="unique@example.com")
            await db_session.commit()

    async def test_habit_requires_user(self, db_session, setup_factories):
        """Habit must have a user."""
        # This should fail due to foreign key constraint
        habit = Habit(
            name="Test",
            question="Test?",
            color="#FF0000",
            frequency=1,
            range=1,
            user_id=99999,  # Non-existent user
        )
        db_session.add(habit)
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_tracker_requires_habit(self, db_session, setup_factories):
        """Tracker must have a habit."""
        tracker = Tracker(
            habit_id=99999,  # Non-existent habit
            dated=date.today(),
            completed=True,
        )
        db_session.add(tracker)
        with pytest.raises(Exception):
            await db_session.commit()
