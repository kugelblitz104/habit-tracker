"""Test data factories."""

import random
from datetime import date, datetime

from factory.alchemy import SQLAlchemyModelFactory
from factory.declarations import LazyFunction, SubFactory
from factory.faker import Faker
from factory.helpers import post_generation
from passlib.context import CryptContext

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.security import get_password_hash
from habit_tracker.schemas.db_models import Habit, Tracker, User

cached_password_hash = get_password_hash("password123")


_test_pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4
)


def get_fast_password_hash(password: str) -> str:
    """Get password hash using fast bcrypt rounds for tests."""
    return _test_pwd_context.hash(password)


class BaseFactory(SQLAlchemyModelFactory):
    """Base factory with session management.

    Note: For async sessions, factories build objects but don't auto-persist.
    You must manually add to session and commit/flush in your tests.
    """

    class Meta:
        abstract = True
        sqlalchemy_session = None
        # Don't auto-persist - async sessions require await
        sqlalchemy_session_persistence = None


class UserFactory(BaseFactory):
    """Factory for creating test users."""

    class Meta:
        model = User

    username = Faker("user_name")
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    email = Faker("email")
    # Use cached hash - avoids expensive bcrypt for every user creation
    password_hash = cached_password_hash
    is_admin = False
    created_date = LazyFunction(datetime.now)

    @post_generation
    def with_plain_password(obj, create, extracted, **kwargs):
        """Allow setting plaintext password for testing."""
        if extracted:
            obj.password_hash = get_fast_password_hash(extracted)


class AdminUserFactory(UserFactory):
    """Factory for creating admin users."""

    is_admin = True


class HabitFactory(BaseFactory):
    """Factory for creating test habits."""

    class Meta:
        model = Habit

    name = Faker("text", max_nb_chars=50)
    question = Faker("sentence", nb_words=5, variable_nb_words=True)
    color = Faker("color")
    frequency = LazyFunction(lambda: random.randint(1, 7))
    range = LazyFunction(lambda: random.randint(1, 30))
    reminder = False
    notes = Faker("paragraph", nb_sentences=3, variable_nb_sentences=True)
    archived = False
    sort_order = 0
    user = SubFactory(UserFactory)
    created_date = LazyFunction(datetime.now)


class TrackerFactory(BaseFactory):
    """Factory for creating test trackers."""

    class Meta:
        model = Tracker

    habit = SubFactory(HabitFactory)
    dated = LazyFunction(date.today)
    status = TrackerStatus.COMPLETED
    note = Faker("sentence")
    created_date = LazyFunction(datetime.now)


class CompletedTrackerFactory(TrackerFactory):
    """Factory for completed trackers."""

    status = TrackerStatus.COMPLETED


class IncompleteTrackerFactory(TrackerFactory):
    """Factory for creating incomplete tracker (neither completed nor skipped)."""

    status = TrackerStatus.NOT_COMPLETED


class SkippedTrackerFactory(TrackerFactory):
    """Factory for skipped trackers."""

    status = TrackerStatus.SKIPPED
