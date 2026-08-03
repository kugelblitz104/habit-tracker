"""Test data factories."""

import random
from datetime import date, datetime

from factory.alchemy import SQLAlchemyModelFactory
from factory.declarations import LazyAttribute, LazyFunction, Sequence, SubFactory
from factory.faker import Faker
from factory.helpers import post_generation
from passlib.context import CryptContext

from habit_tracker.constants import TaskStatus, TimeEntryKind, TrackerStatus
from habit_tracker.core.crypto import encrypt_secret
from habit_tracker.core.slugs import slugify
from habit_tracker.schemas.db_models import (
    CalendarConnection,
    Countdown,
    Habit,
    IntegrationConnection,
    Profile,
    Project,
    Task,
    TimeEntry,
    Tracker,
    User,
)

_test_pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4
)

# Hash once with the cheap 4-round context. The previous version used the
# production context (bcrypt, 12 rounds) at import time, which made every
# /auth/login in tests pay a ~300ms full-cost bcrypt verify - the verify cost
# is encoded in the hash itself, so the fast_password_hashing fixture could
# not help.
cached_password_hash = _test_pwd_context.hash("password123")


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

    @post_generation
    def default_profile(obj, create, extracted, **kwargs):
        """Give every new user a default profile.

        Habit creation resolves a profile for the habit and returns 400 for
        profile-less users, so API tests need users that own at least one
        profile (mirrors the register endpoint and the migration backfill).
        Pass ``default_profile=False`` to create a bare, profile-less user.
        """
        if extracted is False:
            return
        ProfileFactory(user=obj)


class AdminUserFactory(UserFactory):
    """Factory for creating admin users."""

    is_admin = True


class ProfileFactory(BaseFactory):
    """Factory for creating test profiles."""

    class Meta:
        model = Profile

    # Profile names are unique per user - a Sequence avoids the collisions
    # that Faker("word") produced
    name = Sequence(lambda n: f"Profile {n}")
    color_start = "#e0763f"
    color_end = "#c14e6a"
    habits_enabled = True
    countdowns_enabled = True
    insights_enabled = True
    calendar_enabled = True
    publish_to_azure = False
    default_landing = "today"
    week_start_monday = True
    use_habit_color_accent = False
    show_estimated_effort = False
    pomodoro_work_minutes = 25
    pomodoro_break_minutes = 5
    pomodoro_long_break_minutes = 15
    pomodoro_cycles = 4
    user = SubFactory(UserFactory)
    created_date = LazyFunction(datetime.now)
    updated_date = None


class HabitFactory(BaseFactory):
    """Factory for creating test habits."""

    class Meta:
        model = Habit
        # `user` is a factory-only param - Habit has no user_id column. It
        # means "a habit in this user's default profile", which is what the
        # ~181 HabitFactory(user=...) call sites want. If both `user=` and
        # `profile=` are passed, `profile=` wins.
        exclude = ("user",)

    name = Faker("text", max_nb_chars=50)
    # Derived from the name, like TaskFactory.slug - see the note there.
    slug = LazyAttribute(lambda o: slugify(o.name))
    question = Faker("sentence", nb_words=5, variable_nb_words=True)
    color = Faker("color")
    frequency = LazyFunction(lambda: random.randint(1, 7))
    range = LazyFunction(lambda: random.randint(1, 30))
    reminder = False
    notes = Faker("paragraph", nb_sentences=3, variable_nb_sentences=True)
    archived = False
    sort_order = 0
    category = None
    user = SubFactory(UserFactory)
    # Reuse the user's existing (default) profile so a user's habits share one
    # profile; only create a profile if the user somehow has none.
    profile = LazyAttribute(
        lambda habit: (
            habit.user.profiles[0]
            if habit.user.profiles
            else ProfileFactory(user=habit.user)
        )
    )
    created_date = LazyFunction(datetime.now)


class ProjectFactory(BaseFactory):
    """Factory for creating test projects."""

    class Meta:
        model = Project

    name = Faker("text", max_nb_chars=50)
    # Derived from the name, like TaskFactory.slug - see the note there.
    slug = LazyAttribute(lambda o: slugify(o.name))
    color = Faker("color")
    notes = Faker("paragraph", nb_sentences=3, variable_nb_sentences=True)
    archived = False
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)


class CountdownFactory(BaseFactory):
    """Factory for creating test countdowns."""

    class Meta:
        model = Countdown

    task = None
    title = Sequence(lambda n: f"Countdown {n}")
    target_date = LazyFunction(date.today)
    target_time = None
    category = None
    color = None
    repeat = "none"
    show_occurrence = False
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)
    updated_date = None


class CalendarConnectionFactory(BaseFactory):
    """Factory for creating test calendar connections."""

    class Meta:
        model = CalendarConnection

    name = Sequence(lambda n: f"Calendar {n}")
    color = "#3366cc"
    url = Sequence(lambda n: f"https://calendar.example.com/feed-{n}.ics")
    provider = "Google"
    enabled = True
    cached_ics = None
    last_fetched_at = None
    etag = None
    last_error = None
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)


class IntegrationConnectionFactory(BaseFactory):
    """Factory for creating test integration connections (GitHub by default)."""

    class Meta:
        model = IntegrationConnection

    provider = "github"
    name = Sequence(lambda n: f"Integration {n}")
    # Store a real Fernet ciphertext so decrypt in the router round-trips.
    encrypted_token = LazyFunction(lambda: encrypt_secret("test-pat-123"))
    organization = None
    project = None
    work_item_type = None
    default_repo = "octocat/hello-world"
    enabled = True
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)


class TaskFactory(BaseFactory):
    """Factory for creating test tasks."""

    class Meta:
        model = Task

    title = Faker("sentence", nb_words=4, variable_nb_words=True)
    # Derived from the title the same way the API derives it, because `slug` is
    # NOT NULL. Deliberately NOT collision-aware: the numbered-suffix rule lives
    # in `allocate_task_slug`, and duplicating it here would mean a second
    # implementation to keep in step. Two factory tasks with the same title in
    # one profile therefore share a slug, which the schema allows (the column is
    # indexed, not unique) - tests that care about numbering create tasks through
    # the API instead, in TestTaskSlugs.
    slug = LazyAttribute(lambda o: slugify(o.title))
    notes = None
    priority = 0
    status = TaskStatus.OPEN
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)


class DoneTaskFactory(TaskFactory):
    """Factory for completed tasks."""

    status = TaskStatus.DONE
    closed_date = LazyFunction(datetime.now)


class TimeEntryFactory(BaseFactory):
    """Factory for creating test time entries (completed by default)."""

    class Meta:
        model = TimeEntry

    kind = TimeEntryKind.STOPWATCH
    started_at = LazyFunction(datetime.now)
    ended_at = LazyFunction(datetime.now)
    duration_seconds = 0
    note = None
    task = None
    profile = SubFactory(ProfileFactory)
    created_date = LazyFunction(datetime.now)


class RunningTimeEntryFactory(TimeEntryFactory):
    """Factory for a running (not-yet-stopped) time entry."""

    ended_at = None
    duration_seconds = None


class TrackerFactory(BaseFactory):
    """Factory for creating test trackers."""

    class Meta:
        model = Tracker

    habit = SubFactory(HabitFactory)
    dated = LazyFunction(date.today)
    status = TrackerStatus.COMPLETED
    note = Faker("sentence")
    created_date = LazyFunction(datetime.now)
