"""Tests for the profile-scoped bulk-delete endpoints.

Each of projects / tasks / countdowns / time-entries exposes a
``DELETE /?profile_id=`` that removes every row in one profile, leaving
other profiles untouched and honoring the same FK side effects as the
single-row deletes.
"""

from datetime import date

from sqlalchemy import select

from habit_tracker.schemas.db_models import (
    Countdown,
    Habit,
    Project,
    Task,
    TimeEntry,
    Tracker,
)
from tests.factories import (
    HabitFactory,
    ProfileFactory,
    ProjectFactory,
    RunningTimeEntryFactory,
    TaskFactory,
    TimeEntryFactory,
    TrackerFactory,
    UserFactory,
)

BULK_DELETE_PATHS = (
    "/projects/",
    "/tasks/",
    "/countdowns/",
    "/time-entries/",
    "/habits/",
    "/trackers/",
)


async def login_as(client, user):
    """Log in as the given user and attach the bearer token to the client."""
    login_response = await client.post(
        "/auth/login",
        data={"username": user.username, "password": "password123"},
    )
    token = login_response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})


class TestBulkDeleteAuth:
    """Auth/validation shared across every bulk-delete endpoint."""

    async def test_requires_profile_id(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path)
            assert response.status_code == 422, path

    async def test_foreign_profile_forbidden(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(client, user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path, params={"profile_id": foreign.id})
            assert response.status_code == 403, path

    async def test_unknown_profile_not_found(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        for path in BULK_DELETE_PATHS:
            response = await client.delete(path, params={"profile_id": 99999})
            assert response.status_code == 404, path


class TestBulkDeleteProjects:
    async def test_deletes_only_this_profile(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        ProjectFactory(profile=profile)
        ProjectFactory(profile=profile)
        keep = ProjectFactory(profile=other)
        await db_session.commit()

        await login_as(client, user)
        response = await client.delete("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Project))).scalars().all()
        assert [p.id for p in remaining] == [keep.id]

    async def test_tasks_kept_and_unassigned(
        self, client, db_session, setup_factories
    ):
        """Deleting all projects keeps their tasks but clears project_id."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        task = TaskFactory(profile=profile, project_id=project.id)
        await db_session.commit()
        task_id = task.id

        await login_as(client, user)
        response = await client.delete("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200

        db_session.expire_all()
        surviving = await db_session.get(Task, task_id)
        assert surviving is not None
        assert surviving.project_id is None


class TestBulkDeleteTasks:
    async def test_deletes_tasks_and_subtasks(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()
        TaskFactory(profile=profile, parent_id=parent.id)  # subtask
        keep = TaskFactory(profile=other)
        await db_session.commit()

        await login_as(client, user)
        response = await client.delete("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2  # parent + subtask

        remaining = (await db_session.execute(select(Task))).scalars().all()
        assert [t.id for t in remaining] == [keep.id]

    async def test_cascades_time_entries_but_unlinks_countdowns(
        self, client, db_session, setup_factories
    ):
        """A task-attached time entry is removed with the task (CASCADE); a
        countdown that links the task is kept and unlinked (SET NULL)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        entry = TimeEntryFactory(profile=profile, task=task)
        countdown = Countdown(
            profile_id=profile.id,
            task_id=task.id,
            title="Ship it",
            target_date=date.today(),
        )
        db_session.add(countdown)
        await db_session.commit()
        entry_id, countdown_id = entry.id, countdown.id

        await login_as(client, user)
        response = await client.delete("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200

        db_session.expire_all()
        assert await db_session.get(TimeEntry, entry_id) is None  # cascaded
        survivor = await db_session.get(Countdown, countdown_id)
        assert survivor is not None and survivor.task_id is None  # unlinked


class TestBulkDeleteCountdowns:
    async def test_deletes_only_this_profile(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        db_session.add_all(
            [
                Countdown(
                    profile_id=profile.id, title="A", target_date=date.today()
                ),
                Countdown(
                    profile_id=profile.id, title="B", target_date=date.today()
                ),
                Countdown(
                    profile_id=other.id, title="Keep", target_date=date.today()
                ),
            ]
        )
        await db_session.commit()

        await login_as(client, user)
        response = await client.delete(
            "/countdowns/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Countdown))).scalars().all()
        assert [c.title for c in remaining] == ["Keep"]


class TestBulkDeleteTimeEntries:
    async def test_deletes_running_and_completed_only_this_profile(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        TimeEntryFactory(profile=profile)
        RunningTimeEntryFactory(profile=profile)  # unstopped entry is removed too
        keep = TimeEntryFactory(profile=other)
        await db_session.commit()

        await login_as(client, user)
        response = await client.delete(
            "/time-entries/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(TimeEntry))).scalars().all()
        assert [e.id for e in remaining] == [keep.id]


class TestBulkDeleteHabits:
    async def test_deletes_habits_and_trackers_only_this_profile(
        self, client, db_session, setup_factories
    ):
        """Deleting all habits in a profile also removes their trackers
        (CASCADE) and leaves another profile's habits alone."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=profile)
        HabitFactory(user=user, profile=profile)
        keep = HabitFactory(user=user, profile=other)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        tracker_id = tracker.id

        await login_as(client, user)
        response = await client.delete("/habits/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Habit))).scalars().all()
        assert [h.id for h in remaining] == [keep.id]
        # Trackers of the deleted habits are gone too (expire first so the
        # check re-reads from the DB rather than the session identity map).
        db_session.expire_all()
        assert await db_session.get(Tracker, tracker_id) is None


class TestBulkDeleteTrackers:
    async def test_deletes_trackers_keeps_habits_only_this_profile(
        self, client, db_session, setup_factories
    ):
        """Deleting all trackers in a profile keeps the habits and leaves
        another profile's trackers untouched."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=profile)
        other_habit = HabitFactory(user=user, profile=other)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date(2026, 1, 1))
        TrackerFactory(habit=habit, dated=date(2026, 1, 2))
        keep = TrackerFactory(habit=other_habit, dated=date(2026, 1, 1))
        await db_session.commit()
        habit_id, keep_id = habit.id, keep.id

        await login_as(client, user)
        response = await client.delete("/trackers/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Tracker))).scalars().all()
        assert [t.id for t in remaining] == [keep_id]
        # The habit itself survives.
        assert await db_session.get(Habit, habit_id) is not None
