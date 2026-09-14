"""Tests for task management endpoints."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from habit_tracker.constants import TaskStatus
from habit_tracker.schemas.db_models import Countdown, Task, TimeEntry
from tests.factories import (
    AdminUserFactory,
    CountdownFactory,
    DoneTaskFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    TimeEntryFactory,
    UserFactory,
)


class TestCreateTask:
    """Tests for POST /tasks/ endpoint."""

    async def test_create_task_quick_capture(self, client, db_session, login_as):
        """Only profile_id and title are required; everything else defaults."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Buy milk"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Buy milk"
        assert data["profile_id"] == profile.id
        assert data["status"] == TaskStatus.OPEN
        assert data["priority"] == 0
        assert data["project_id"] is None
        assert data["due_date"] is None
        assert data["closed_date"] is None

    async def test_create_task_all_fields(self, client, db_session, login_as):
        """Create task with a full payload and get it echoed back."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        due = date.today() + timedelta(days=1)

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Book venue",
                "notes": "Call three venues",
                "priority": 3,
                "due_date": due.isoformat(),
                "due_time": "14:30:00",
                "status": TaskStatus.IN_PROGRESS.value,
                "block_reason": None,
                "external_ref": "ADO-2841",
                "external_url": "https://dev.azure.com/x/2841",
                "project_id": project.id,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Book venue"
        assert data["notes"] == "Call three venues"
        assert data["priority"] == 3
        assert data["due_date"] == due.isoformat()
        assert data["due_time"] == "14:30:00"
        assert data["status"] == TaskStatus.IN_PROGRESS
        assert data["external_ref"] == "ADO-2841"
        assert data["external_url"] == "https://dev.azure.com/x/2841"
        assert data["project_id"] == project.id

    async def test_create_task_with_scheduled_date_time(
        self, client, db_session, login_as
    ):
        """scheduled_date/scheduled_time persist and round-trip in TaskRead."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Dentist",
                "status": TaskStatus.SCHEDULED.value,
                "scheduled_date": scheduled.isoformat(),
                "scheduled_time": "09:15:00",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["scheduled_date"] == scheduled.isoformat()
        assert data["scheduled_time"] == "09:15:00"

        # Round-trips on a fresh GET too
        response = await client.get(f"/tasks/{data['id']}")
        assert response.status_code == 200
        got = response.json()
        assert got["scheduled_date"] == scheduled.isoformat()
        assert got["scheduled_time"] == "09:15:00"

    async def test_create_non_scheduled_task_clears_scheduled_data(
        self, client, db_session, login_as
    ):
        """A non-SCHEDULED status forces scheduled_date/time null even if sent."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Buy milk",
                "status": TaskStatus.OPEN.value,
                "scheduled_date": scheduled.isoformat(),
                "scheduled_time": "09:15:00",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == TaskStatus.OPEN
        assert data["scheduled_date"] is None
        assert data["scheduled_time"] is None

        # Confirm it was persisted as null, not just scrubbed in the response
        db_task = await db_session.get(Task, data["id"])
        await db_session.refresh(db_task)
        assert db_task.scheduled_date is None
        assert db_task.scheduled_time is None

    async def test_create_scheduled_task_keeps_scheduled_data(
        self, client, db_session, login_as
    ):
        """A SCHEDULED status keeps supplied scheduled_date/time."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Dentist",
                "status": TaskStatus.SCHEDULED.value,
                "scheduled_date": scheduled.isoformat(),
                "scheduled_time": "09:15:00",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == TaskStatus.SCHEDULED
        assert data["scheduled_date"] == scheduled.isoformat()
        assert data["scheduled_time"] == "09:15:00"

    async def test_create_task_project_in_other_profile(
        self, client, db_session, login_as
    ):
        """A project in a different profile is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project = ProjectFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Mismatched",
                "project_id": project.id,
            },
        )
        assert response.status_code == 400

    async def test_create_task_foreign_or_missing_profile(
        self, client, db_session, login_as
    ):
        """Foreign profile is 403; non-existent profile is 404."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/", json={"profile_id": foreign.id, "title": "Nope"}
        )
        assert response.status_code == 403

        response = await client.post(
            "/tasks/", json={"profile_id": 99999, "title": "Nope"}
        )
        assert response.status_code == 404

    async def test_create_task_done_stamps_closed_date(
        self, client, db_session, login_as
    ):
        """Creating a task already DONE stamps its closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Already done",
                "status": TaskStatus.DONE.value,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == TaskStatus.DONE
        assert data["closed_date"] is not None


class TestListTasks:
    """Tests for GET /tasks/ endpoint."""

    async def test_list_tasks_excludes_closed_by_default(
        self, client, db_session, login_as
    ):
        """DONE and CANCELLED tasks are excluded unless include_closed."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        open_task = TaskFactory(profile=profile, status=TaskStatus.OPEN)
        blocked_task = TaskFactory(profile=profile, status=TaskStatus.BLOCKED)
        DoneTaskFactory(profile=profile)
        TaskFactory(
            profile=profile, status=TaskStatus.CANCELLED, closed_date=datetime.now()
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {t["id"] for t in data["tasks"]}
        assert ids == {open_task.id, blocked_task.id}

    async def test_list_tasks_include_closed(self, client, db_session, login_as):
        """include_closed=true returns closed tasks too."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(profile=profile, status=TaskStatus.OPEN)
        DoneTaskFactory(profile=profile)
        TaskFactory(
            profile=profile, status=TaskStatus.CANCELLED, closed_date=datetime.now()
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "include_closed": True}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 3

    async def test_list_tasks_status_filter_includes_done(
        self, client, db_session, login_as
    ):
        """An explicit status filter works even for DONE."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(profile=profile, status=TaskStatus.OPEN)
        done = DoneTaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/",
            params={"profile_id": profile.id, "status": TaskStatus.DONE.value},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["id"] == done.id

    async def test_list_tasks_closed_only_excludes_active(
        self, client, db_session, login_as
    ):
        """closed_only returns done/cancelled tasks without include_closed."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        done = DoneTaskFactory(profile=profile)
        cancelled = TaskFactory(profile=profile, status=TaskStatus.CANCELLED)
        TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "closed_only": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {t["id"] for t in data["tasks"]} == {done.id, cancelled.id}

    async def test_list_tasks_completed_view_ordering(
        self, client, db_session, login_as
    ):
        """closed_only=true orders by closed_date descending."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        oldest = DoneTaskFactory(
            profile=profile, closed_date=datetime(2026, 1, 1, 9, 0)
        )
        middle = TaskFactory(
            profile=profile,
            status=TaskStatus.CANCELLED,
            closed_date=datetime(2026, 1, 2, 9, 0),
        )
        newest = DoneTaskFactory(
            profile=profile, closed_date=datetime(2026, 1, 3, 9, 0)
        )
        TaskFactory(profile=profile)  # open task stays out of the closed view
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/",
            params={"profile_id": profile.id, "closed_only": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert [t["id"] for t in data["tasks"]] == [newest.id, middle.id, oldest.id]

    async def test_list_tasks_active_ordering(self, client, db_session, login_as):
        """Active tasks order by priority desc, due date asc nulls last."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        today = date.today()
        base = datetime.now()
        prio3 = TaskFactory(profile=profile, priority=3, created_date=base)
        prio2_due_near = TaskFactory(
            profile=profile,
            priority=2,
            due_date=today + timedelta(days=2),
            created_date=base,
        )
        prio2_due_far = TaskFactory(
            profile=profile,
            priority=2,
            due_date=today + timedelta(days=9),
            created_date=base,
        )
        prio2_no_due = TaskFactory(
            profile=profile, priority=2, created_date=base + timedelta(seconds=1)
        )
        prio0_due = TaskFactory(
            profile=profile,
            priority=0,
            due_date=today + timedelta(days=1),
            created_date=base,
        )
        prio0_no_due = TaskFactory(
            profile=profile, priority=0, created_date=base + timedelta(seconds=2)
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert [t["id"] for t in response.json()["tasks"]] == [
            prio3.id,
            prio2_due_near.id,
            prio2_due_far.id,
            prio2_no_due.id,
            prio0_due.id,
            prio0_no_due.id,
        ]

    async def test_list_tasks_pagination_after_closed_only_filter(
        self, client, db_session, login_as
    ):
        """limit/offset apply to the closed_only list; total matches it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        # Five closed tasks, closed oldest-first, so index 4 is most recent
        closed = [
            DoneTaskFactory(profile=profile, closed_date=datetime(2026, 1, 1 + i, 9, 0))
            for i in range(5)
        ]
        # Two active tasks that must not affect the paging or the total
        TaskFactory(profile=profile)
        TaskFactory(profile=profile, priority=1)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/",
            params={
                "profile_id": profile.id,
                "closed_only": True,
                "limit": 2,
                "offset": 2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 2
        # Ordered by closed date descending, the slice skips the two newest
        assert [t["id"] for t in data["tasks"]] == [closed[2].id, closed[1].id]

    async def test_list_tasks_project_filter(self, client, db_session, login_as):
        """project_id filter restricts results to that project's tasks."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        in_project = TaskFactory(profile=profile, project=project)
        TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "project_id": project.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["id"] == in_project.id

    async def test_list_tasks_parent_filter(self, client, db_session, login_as):
        """parent_id filter returns only that parent's subtasks."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Parent")
        other_parent = TaskFactory(profile=profile, title="Other parent")
        await db_session.commit()

        subtask = TaskFactory(profile=profile, parent=parent, title="Mine")
        TaskFactory(profile=profile, parent=other_parent, title="Not mine")
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "parent_id": parent.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [t["id"] for t in data["tasks"]] == [subtask.id]
        # Subtasks nest exactly one level deep, so a filtered row never has
        # children of its own - the counts stay 0/0 without the aggregate.
        assert data["tasks"][0]["subtask_count"] == 0
        assert data["tasks"][0]["subtask_done_count"] == 0

    async def test_list_tasks_parent_filter_include_closed(
        self, client, db_session, login_as
    ):
        """parent_id composes with include_closed like any other filter."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Parent")
        await db_session.commit()

        open_sub = TaskFactory(profile=profile, parent=parent)
        done_sub = DoneTaskFactory(profile=profile, parent=parent)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "parent_id": parent.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert [t["id"] for t in data["tasks"]] == [open_sub.id]

        response = await client.get(
            "/tasks/",
            params={
                "profile_id": profile.id,
                "parent_id": parent.id,
                "include_closed": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {t["id"] for t in data["tasks"]} == {open_sub.id, done_sub.id}

    async def test_list_tasks_parent_filter_reaches_past_the_page_cap(
        self, client, db_session, login_as
    ):
        """Subtasks stay reachable once the profile outgrows a single page.

        The bug this filter exists for: subtasks are priority 0 with no due
        date, so the default ordering puts them last. Once a profile holds more
        than `limit` tasks they fall off page one entirely, and a client that
        filtered the list by parent_id itself saw a task's subtasks disappear
        while its subtask_count still said it had some.
        """
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        # 99 high-priority tasks plus the parent fill page one exactly, leaving
        # the two subtasks as the only rows past the cap
        for _ in range(99):
            TaskFactory(profile=profile, priority=3)
        parent = TaskFactory(profile=profile, priority=3, title="Parent")
        await db_session.commit()

        subtasks = [TaskFactory(profile=profile, parent=parent) for _ in range(2)]
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 102
        assert len(data["tasks"]) == 100
        page_one_ids = {t["id"] for t in data["tasks"]}
        # Neither subtask made page one, but the parent still reports them
        assert page_one_ids.isdisjoint({s.id for s in subtasks})
        parent_row = next(t for t in data["tasks"] if t["id"] == parent.id)
        assert parent_row["subtask_count"] == 2

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "parent_id": parent.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {t["id"] for t in data["tasks"]} == {s.id for s in subtasks}

    async def test_list_tasks_parent_filter_unknown_or_foreign_parent(
        self, client, db_session, login_as
    ):
        """parent_id is a filter, not a fetch: no match means an empty list.

        A parent in another profile can't leak rows either - the profile filter
        still applies, so the two conditions simply never overlap.
        """
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        other_profile = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        foreign_parent = TaskFactory(profile=other_profile, title="Their parent")
        await db_session.commit()

        TaskFactory(profile=other_profile, parent=foreign_parent)
        TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/",
            params={"profile_id": profile.id, "parent_id": foreign_parent.id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["tasks"] == []

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "parent_id": 99999}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_list_tasks_foreign_or_missing_profile(
        self, client, db_session, login_as
    ):
        """Foreign profile is 403; non-existent profile is 404."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/", params={"profile_id": foreign.id})
        assert response.status_code == 403

        response = await client.get("/tasks/", params={"profile_id": 99999})
        assert response.status_code == 404


class TestGetTask:
    """Tests for GET /tasks/{task_id} endpoint."""

    async def test_get_own_task(self, client, db_session, login_as):
        """User can retrieve their own task."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=3)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task.id

    async def test_get_task_as_admin(self, client, db_session, login_as):
        """Admin can access any task."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 200

    async def test_get_other_user_task(self, client, db_session, login_as):
        """User cannot access a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 403

    async def test_get_nonexistent_task(self, client, db_session, login_as):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/99999")
        assert response.status_code == 404


class TestTaskSlugs:
    """Tests for server-assigned slugs and GET /tasks/by-slug/{slug}.

    The pure slugify/numbering rules are pinned DB-free in test_slugs.py; this
    class covers allocation against real rows (uniqueness scope, re-slug on
    rename) and the lookup endpoint.
    """

    async def test_create_assigns_slug_from_title(self, client, db_session, login_as):
        """A created task comes back with a slug derived from its title."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Setup Utilities"}
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "setup-utilities"

    async def test_duplicate_titles_number_off_each_other(
        self, client, db_session, login_as
    ):
        """The first task keeps the clean slug; the next gets -2, then -3."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        slugs = []
        for _ in range(3):
            response = await client.post(
                "/tasks/", json={"profile_id": profile.id, "title": "Follow up"}
            )
            assert response.status_code == 201
            slugs.append(response.json()["slug"])

        assert slugs == ["follow-up", "follow-up-2", "follow-up-3"]

    async def test_slug_uniqueness_is_per_profile(self, client, db_session, login_as):
        """The same title in two profiles keeps the clean slug in both."""
        user = UserFactory()
        await db_session.commit()

        first = ProfileFactory(user=user, name="Personal")
        second = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(user)

        for profile in (first, second):
            response = await client.post(
                "/tasks/", json={"profile_id": profile.id, "title": "Follow up"}
            )
            assert response.status_code == 201
            assert response.json()["slug"] == "follow-up"

    async def test_unslugifiable_title_still_gets_a_slug(
        self, client, db_session, login_as
    ):
        """An all-digit title would collide with the numeric id route, so it
        takes the fallback prefix. Every task has a slug: the column is NOT
        NULL, like the title it derives from."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "2841"}
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "task-2841"

        # And it resolves, rather than being reachable only by id.
        found = await client.get(
            "/tasks/by-slug/task-2841", params={"profile_id": profile.id}
        )
        assert found.status_code == 200
        assert found.json()["id"] == response.json()["id"]

    async def test_titles_that_share_a_fallback_slug_are_numbered(
        self, client, db_session, login_as
    ):
        """Two titles that each yield nothing on their own don't collide."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        slugs = []
        for title in ("???", "日本語"):
            response = await client.post(
                "/tasks/", json={"profile_id": profile.id, "title": title}
            )
            assert response.status_code == 201
            slugs.append(response.json()["slug"])

        assert slugs == ["task", "task-2"]

    async def test_get_by_slug_returns_the_task(self, client, db_session, login_as):
        """The by-slug response matches the by-id one, counts included."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/",
            json={"profile_id": profile.id, "title": "Setup Utilities", "priority": 3},
        )
        task_id = created.json()["id"]

        response = await client.get(
            "/tasks/by-slug/setup-utilities", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task_id
        assert data["slug"] == "setup-utilities"

        by_id = await client.get(f"/tasks/{task_id}")
        assert by_id.json() == data

    async def test_get_by_slug_includes_subtask_counts(
        self, client, db_session, login_as
    ):
        """Subtask counts are aggregated for the by-slug response too."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        parent = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Parent task"}
        )
        parent_id = parent.json()["id"]

        for title, task_status in (("Sub one", TaskStatus.DONE), ("Sub two", None)):
            payload = {
                "profile_id": profile.id,
                "title": title,
                "parent_id": parent_id,
            }
            if task_status is not None:
                payload["status"] = task_status
            assert (await client.post("/tasks/", json=payload)).status_code == 201

        response = await client.get(
            "/tasks/by-slug/parent-task", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json()["subtask_count"] == 2
        assert response.json()["subtask_done_count"] == 1

    async def test_get_by_slug_unknown_slug_404(self, client, db_session, login_as):
        """An unknown slug is a 404, not an empty 200."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/by-slug/nothing-here", params={"profile_id": profile.id}
        )
        assert response.status_code == 404

    async def test_get_by_slug_does_not_cross_profiles(
        self, client, db_session, login_as
    ):
        """A slug is only looked up inside the profile it was asked for, even
        when the caller owns both profiles."""
        user = UserFactory()
        await db_session.commit()

        personal = ProfileFactory(user=user, name="Personal")
        work = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/", json={"profile_id": personal.id, "title": "Setup Utilities"}
        )
        assert created.status_code == 201

        response = await client.get(
            "/tasks/by-slug/setup-utilities", params={"profile_id": work.id}
        )
        assert response.status_code == 404

    async def test_get_by_slug_other_users_profile_403(
        self, client, db_session, login_as
    ):
        """Ownership is checked on the profile before any lookup happens."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/tasks/by-slug/anything", params={"profile_id": foreign_profile.id}
        )
        assert response.status_code == 403

    async def test_rename_reslugs_and_old_slug_stops_resolving(
        self, client, db_session, login_as
    ):
        """The slug tracks the title: after a rename the new slug resolves, the
        old one 404s, and the numeric URL keeps working throughout."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Setup Utilities"}
        )
        task_id = created.json()["id"]

        patched = await client.patch(
            f"/tasks/{task_id}", json={"title": "Configure Utilities"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "configure-utilities"

        stale = await client.get(
            "/tasks/by-slug/setup-utilities", params={"profile_id": profile.id}
        )
        assert stale.status_code == 404

        fresh = await client.get(
            "/tasks/by-slug/configure-utilities", params={"profile_id": profile.id}
        )
        assert fresh.status_code == 200
        assert fresh.json()["id"] == task_id

        assert (await client.get(f"/tasks/{task_id}")).status_code == 200

    async def test_rename_to_same_slug_does_not_bump_itself(
        self, client, db_session, login_as
    ):
        """Re-slugging excludes the task's own row, so a title edit that yields
        the same slug keeps it instead of colliding with itself and taking -2."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Setup Utilities"}
        )
        task_id = created.json()["id"]
        assert created.json()["slug"] == "setup-utilities"

        patched = await client.patch(
            f"/tasks/{task_id}", json={"title": "Setup   utilities!"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "setup-utilities"

    async def test_patch_without_title_keeps_the_slug(
        self, client, db_session, login_as
    ):
        """Editing anything else leaves the slug alone."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Setup Utilities"}
        )
        task_id = created.json()["id"]

        patched = await client.patch(f"/tasks/{task_id}", json={"priority": 2})
        assert patched.status_code == 200
        assert patched.json()["slug"] == "setup-utilities"

    async def test_slug_is_read_only(self, client, db_session, login_as):
        """`slug` is absent from TaskCreate/TaskUpdate, so a client cannot set
        it, so an attempt is ignored and the derived slug wins."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        created = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Setup Utilities",
                "slug": "hand-picked",
            },
        )
        assert created.status_code == 201
        assert created.json()["slug"] == "setup-utilities"

        task_id = created.json()["id"]
        patched = await client.patch(f"/tasks/{task_id}", json={"slug": "hand-picked"})
        assert patched.status_code == 200
        assert patched.json()["slug"] == "setup-utilities"

    async def test_profile_move_reslugs_against_the_new_profile(
        self, client, db_session, login_as
    ):
        """Slugs are unique per profile, so moving a task into a profile that
        already uses its slug numbers the moved task off the existing one."""
        user = UserFactory()
        await db_session.commit()

        personal = ProfileFactory(user=user, name="Personal")
        work = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(user)

        incumbent = await client.post(
            "/tasks/", json={"profile_id": work.id, "title": "Follow up"}
        )
        assert incumbent.json()["slug"] == "follow-up"

        mover = await client.post(
            "/tasks/", json={"profile_id": personal.id, "title": "Follow up"}
        )
        assert mover.json()["slug"] == "follow-up"

        moved = await client.patch(
            f"/tasks/{mover.json()['id']}", json={"profile_id": work.id}
        )
        assert moved.status_code == 200
        assert moved.json()["slug"] == "follow-up-2"


class TestPatchTask:
    """Tests for PATCH /tasks/{task_id} endpoint."""

    async def test_patch_task_priority(self, client, db_session, login_as):
        """Raising priority to 3 moves the task from whenever to now."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/tasks/{task.id}", json={"priority": 3})
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == 3

    async def test_patch_task_scheduled_date(self, client, db_session, login_as):
        """Setting a scheduled_date alongside the SCHEDULED status persists it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0)  # starts "whenever"
        await db_session.commit()

        await login_as(user)

        # Scheduled data only lives on SCHEDULED tasks, so schedule + set status
        scheduled = date.today() + timedelta(days=2)
        response = await client.patch(
            f"/tasks/{task.id}",
            json={
                "status": TaskStatus.SCHEDULED.value,
                "scheduled_date": scheduled.isoformat(),
                "scheduled_time": "13:00:00",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scheduled_date"] == scheduled.isoformat()
        assert data["scheduled_time"] == "13:00:00"

    async def test_patch_task_clear_scheduled_date(self, client, db_session, login_as):
        """scheduled_date is nullable - PATCH scheduled_date=null clears it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=2)
        task = TaskFactory(profile=profile, priority=0, scheduled_date=scheduled)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"scheduled_date": None}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scheduled_date"] is None

    async def test_patch_status_away_from_scheduled_clears_scheduled_data(
        self, client, db_session, login_as
    ):
        """Changing status off SCHEDULED clears scheduled data without sending it.

        The scheduled date was the only reason the task was 'soon'; once the
        status leaves SCHEDULED and clears it, the task drops to 'whenever'.
        """
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=2)
        task = TaskFactory(
            profile=profile,
            priority=0,
            status=TaskStatus.SCHEDULED,
            scheduled_date=scheduled,
            scheduled_time=None,
        )
        await db_session.commit()

        await login_as(user)

        # Only the status changes - the scheduled fields are NOT part of the body
        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.OPEN.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.OPEN
        assert data["scheduled_date"] is None
        assert data["scheduled_time"] is None

        # Persisted as null, not just scrubbed in the response
        db_task = await db_session.get(Task, task.id)
        await db_session.refresh(db_task)
        assert db_task.scheduled_date is None
        assert db_task.scheduled_time is None

    async def test_patch_scheduled_task_keeps_scheduled_date(
        self, client, db_session, login_as
    ):
        """Patching scheduled_date while status stays SCHEDULED keeps it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(
            profile=profile,
            priority=0,
            status=TaskStatus.SCHEDULED,
            scheduled_date=date.today() + timedelta(days=10),
        )
        await db_session.commit()

        await login_as(user)

        new_scheduled = date.today() + timedelta(days=2)
        response = await client.patch(
            f"/tasks/{task.id}",
            json={"scheduled_date": new_scheduled.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.SCHEDULED
        assert data["scheduled_date"] == new_scheduled.isoformat()

    async def test_patch_non_scheduled_task_to_scheduled_keeps_scheduled_date(
        self, client, db_session, login_as
    ):
        """Setting status to SCHEDULED + scheduled_date in one PATCH keeps it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0, status=TaskStatus.OPEN)
        await db_session.commit()

        await login_as(user)

        scheduled = date.today() + timedelta(days=2)
        response = await client.patch(
            f"/tasks/{task.id}",
            json={
                "status": TaskStatus.SCHEDULED.value,
                "scheduled_date": scheduled.isoformat(),
                "scheduled_time": "13:00:00",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.SCHEDULED
        assert data["scheduled_date"] == scheduled.isoformat()
        assert data["scheduled_time"] == "13:00:00"

    async def test_patch_task_done_sets_closed_date(self, client, db_session, login_as):
        """Setting status to DONE stamps closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, status=TaskStatus.OPEN)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.DONE.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.DONE
        assert data["closed_date"] is not None

    async def test_patch_task_done_to_cancelled_preserves_closed_date(
        self, client, db_session, login_as
    ):
        """DONE -> CANCELLED keeps the original closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = DoneTaskFactory(
            profile=profile, closed_date=datetime(2026, 1, 5, 12, 0, 0)
        )
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.CANCELLED.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.CANCELLED
        assert data["closed_date"] == "2026-01-05T12:00:00"

    async def test_patch_task_reopen_clears_closed_date(
        self, client, db_session, login_as
    ):
        """Reopening a closed task clears its closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = DoneTaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.OPEN.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.OPEN
        assert data["closed_date"] is None

    async def test_patch_task_block_reason_set_and_clear(
        self, client, db_session, login_as
    ):
        """block_reason can be set and cleared."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}",
            json={
                "status": TaskStatus.BLOCKED.value,
                "block_reason": "venue callback",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.BLOCKED
        assert data["block_reason"] == "venue callback"

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"status": TaskStatus.OPEN.value, "block_reason": None},
        )
        assert response.status_code == 200
        assert response.json()["block_reason"] is None

    async def test_patch_task_move_to_project_same_profile(
        self, client, db_session, login_as
    ):
        """Moving a task into a project of the same profile works."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"project_id": project.id}
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == project.id

    async def test_patch_task_move_to_project_in_other_profile(
        self, client, db_session, login_as
    ):
        """Moving a task into a project of a different profile fails (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project = ProjectFactory(profile=other_profile)
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"project_id": project.id}
        )
        assert response.status_code == 400

    async def test_patch_task_profile_move_without_project(
        self, client, db_session, login_as
    ):
        """A task with no project can move to another of the user's profiles."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 200
        assert response.json()["profile_id"] == other_profile.id

    async def test_patch_task_profile_move_with_project_in_old_profile(
        self, client, db_session, login_as
    ):
        """Moving a task whose project stays in the old profile fails (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        task = TaskFactory(profile=profile, project=project)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 400

    async def test_patch_task_profile_move_to_other_user_profile(
        self, client, db_session, login_as
    ):
        """Moving a task to another user's profile fails (400)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Mine")
        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": foreign.id}
        )
        assert response.status_code == 400

    async def test_patch_task_null_title(self, client, db_session, login_as):
        """An explicit null for the non-nullable title is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/tasks/{task.id}", json={"title": None})
        assert response.status_code == 422

    async def test_patch_task_null_profile_id(self, client, db_session, login_as):
        """An explicit null for the non-nullable profile_id is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/tasks/{task.id}", json={"profile_id": None})
        assert response.status_code == 422

    async def test_patch_other_user_task(self, client, db_session, login_as):
        """User cannot patch a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/tasks/{task.id}", json={"title": "Hax"})
        assert response.status_code == 403

    async def test_patch_nonexistent_task(self, client, db_session, login_as):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.patch("/tasks/99999", json={"title": "Ghost"})
        assert response.status_code == 404


class TestSubtasks:
    """Tests for subtasks (self-referential parent_id, one level deep)."""

    async def test_create_subtask(self, client, db_session, login_as):
        """POST with parent_id creates a subtask; parent_id round-trips."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Plan the offsite")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Book the venue",
                "parent_id": parent.id,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["parent_id"] == parent.id
        assert data["subtask_count"] == 0
        assert data["subtask_done_count"] == 0

        # Round-trips on a fresh GET too
        response = await client.get(f"/tasks/{data['id']}")
        assert response.status_code == 200
        assert response.json()["parent_id"] == parent.id

    async def test_create_subtask_parent_not_found(self, client, db_session, login_as):
        """A non-existent parent is rejected (400, mirrors project_id)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={"profile_id": profile.id, "title": "Orphan", "parent_id": 99999},
        )
        assert response.status_code == 400
        assert "Parent task not found" in response.json()["detail"]

    async def test_create_subtask_cross_profile_parent(
        self, client, db_session, login_as
    ):
        """A parent in a different profile is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        parent = TaskFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Mismatched",
                "parent_id": parent.id,
            },
        )
        assert response.status_code == 400
        assert "Parent task not found" in response.json()["detail"]

    async def test_create_subtask_under_subtask(self, client, db_session, login_as):
        """Creating a subtask under a subtask is rejected (400, one level)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()

        subtask = TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": profile.id,
                "title": "Too deep",
                "parent_id": subtask.id,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Subtasks can only be nested one level deep"

    async def test_patch_parent_onto_task_with_subtasks(
        self, client, db_session, login_as
    ):
        """A task that HAS subtasks cannot itself become a subtask (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        other = TaskFactory(profile=profile)
        await db_session.commit()

        TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{parent.id}", json={"parent_id": other.id}
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "A task with subtasks cannot itself become a subtask"
        )

    async def test_patch_self_parent(self, client, db_session, login_as):
        """A task cannot be its own parent (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/tasks/{task.id}", json={"parent_id": task.id})
        assert response.status_code == 400
        assert response.json()["detail"] == "A task cannot be its own parent"

    async def test_patch_set_and_clear_parent(self, client, db_session, login_as):
        """PATCH can attach a task to a parent and detach it again."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"parent_id": parent.id}
        )
        assert response.status_code == 200
        assert response.json()["parent_id"] == parent.id

        response = await client.patch(f"/tasks/{task.id}", json={"parent_id": None})
        assert response.status_code == 200
        assert response.json()["parent_id"] is None

    async def test_patch_parent_of_existing_subtask_one_level(
        self, client, db_session, login_as
    ):
        """PATCHing parent_id to point at a subtask is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        task = TaskFactory(profile=profile)
        await db_session.commit()

        subtask = TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"parent_id": subtask.id}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Subtasks can only be nested one level deep"

    async def test_delete_parent_cascades_subtasks(self, client, db_session, login_as):
        """Deleting a parent task deletes its subtasks (ON DELETE CASCADE)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()

        subtask = TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()
        parent_id, subtask_id = parent.id, subtask.id

        await login_as(user)

        response = await client.delete(f"/tasks/{parent_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Task).filter(Task.id == parent_id))
        assert result.scalar_one_or_none() is None
        result = await db_session.execute(select(Task).filter(Task.id == subtask_id))
        assert result.scalar_one_or_none() is None

    async def test_list_includes_subtasks_with_parent_id_and_counts(
        self, client, db_session, login_as
    ):
        """Subtasks come back in the same list response; counts are right
        with mixed statuses (done counts DONE only, not cancelled)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Parent")
        lone = TaskFactory(profile=profile, title="Lone")
        await db_session.commit()

        sub_open = TaskFactory(profile=profile, parent_id=parent.id)
        DoneTaskFactory(profile=profile, parent_id=parent.id)
        TaskFactory(
            profile=profile,
            parent_id=parent.id,
            status=TaskStatus.CANCELLED,
            closed_date=datetime.now(),
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        by_id = {t["id"]: t for t in response.json()["tasks"]}
        # Default list: parent, lone task and the open subtask (closed excluded)
        assert set(by_id) == {parent.id, lone.id, sub_open.id}

        assert by_id[parent.id]["parent_id"] is None
        assert by_id[parent.id]["subtask_count"] == 3
        assert by_id[parent.id]["subtask_done_count"] == 1  # DONE only

        assert by_id[sub_open.id]["parent_id"] == parent.id
        assert by_id[sub_open.id]["subtask_count"] == 0
        assert by_id[sub_open.id]["subtask_done_count"] == 0

        assert by_id[lone.id]["subtask_count"] == 0
        assert by_id[lone.id]["subtask_done_count"] == 0

    async def test_get_single_task_subtask_counts(self, client, db_session, login_as):
        """GET /tasks/{id} carries the same counts as the list endpoint."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()

        TaskFactory(profile=profile, parent_id=parent.id)
        DoneTaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/tasks/{parent.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["subtask_count"] == 2
        assert data["subtask_done_count"] == 1

    async def test_patch_profile_move_with_subtasks(self, client, db_session, login_as):
        """Moving a task that has subtasks to another profile fails (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()

        TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/tasks/{parent.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Cannot move a task with subtasks to another profile"
        )

    async def test_patch_profile_move_of_subtask(self, client, db_session, login_as):
        """Moving a subtask fails (400) unless parent_id is nulled with it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        parent = TaskFactory(profile=profile)
        await db_session.commit()

        subtask = TaskFactory(profile=profile, parent_id=parent.id)
        await db_session.commit()

        await login_as(user)

        # Parent would be left in the old profile -> rejected
        response = await client.patch(
            f"/tasks/{subtask.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 400
        assert "Parent task not found" in response.json()["detail"]

        # Detaching in the same request makes the move coherent -> allowed
        response = await client.patch(
            f"/tasks/{subtask.id}",
            json={"profile_id": other_profile.id, "parent_id": None},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile_id"] == other_profile.id
        assert data["parent_id"] is None


class TestDeleteTask:
    """Tests for DELETE /tasks/{task_id} endpoint."""

    async def test_delete_own_task(self, client, db_session, login_as):
        """User can delete their task."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()
        task_id = task.id

        await login_as(user)

        response = await client.delete(f"/tasks/{task_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Task).filter(Task.id == task_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_task(self, client, db_session, login_as):
        """User cannot delete a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/tasks/{task.id}")
        assert response.status_code == 403

    async def test_delete_nonexistent_task(self, client, db_session, login_as):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/tasks/99999")
        assert response.status_code == 404


class TestSortTasks:
    """Tests for PUT /tasks/sort endpoint."""

    async def test_sort_tasks_basic(self, client, db_session, login_as):
        """Successfully reorder sibling tasks; first ID gets the lowest sort_order."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Parent")
        await db_session.commit()
        sub1 = TaskFactory(profile=profile, parent=parent, title="Sub 1")
        sub2 = TaskFactory(profile=profile, parent=parent, title="Sub 2")
        sub3 = TaskFactory(profile=profile, parent=parent, title="Sub 3")
        await db_session.commit()

        await login_as(user)

        # Reorder: sub3, sub1, sub2
        response = await client.put(
            "/tasks/sort",
            json=[sub3.id, sub1.id, sub2.id],
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Tasks sorted successfully"

        await db_session.refresh(sub1)
        await db_session.refresh(sub2)
        await db_session.refresh(sub3)
        assert sub3.sort_order == 0
        assert sub1.sort_order == 1
        assert sub2.sort_order == 2

    async def test_sort_tasks_empty_list(self, client, db_session, login_as):
        """An empty task_ids list is rejected."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put("/tasks/sort", json=[])
        assert response.status_code == 400

    async def test_sort_tasks_duplicate_ids(self, client, db_session, login_as):
        """Duplicate task IDs are rejected."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/tasks/sort", json=[task.id, task.id])
        assert response.status_code == 400

    async def test_sort_tasks_not_found(self, client, db_session, login_as):
        """A missing task ID yields 404."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put("/tasks/sort", json=[99999])
        assert response.status_code == 404

    async def test_sort_tasks_forbidden(self, client, db_session, login_as):
        """Reordering a task in another user's profile is forbidden."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()
        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/tasks/sort", json=[task.id])
        assert response.status_code == 403


class TestDeleteAllTasks:
    """Tests for DELETE /tasks/ (bulk delete, profile-scoped)."""

    async def test_deletes_tasks_and_subtasks(self, client, db_session, login_as):
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

        await login_as(user)
        response = await client.delete("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2  # parent + subtask

        remaining = (await db_session.execute(select(Task))).scalars().all()
        assert [t.id for t in remaining] == [keep.id]

    async def test_cascades_time_entries_but_unlinks_countdowns(
        self, client, db_session, login_as
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
        countdown = CountdownFactory(profile=profile, task=task, title="Ship it")
        await db_session.commit()
        entry_id, countdown_id = entry.id, countdown.id

        await login_as(user)
        response = await client.delete("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200

        db_session.expire_all()
        assert await db_session.get(TimeEntry, entry_id) is None  # cascaded
        survivor = await db_session.get(Countdown, countdown_id)
        assert survivor is not None and survivor.task_id is None  # unlinked


class TestClosedDateRangeFilter:
    """Tests for the closed_from/closed_to query params on GET /tasks/."""

    async def test_returns_only_tasks_closed_in_the_half_open_range(
        self, client, db_session, login_as
    ):
        """Half-open so consecutive days tile without overlapping: a task
        closed exactly at `closed_to` belongs to the next window."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        before = TaskFactory(
            profile=profile,
            title="Before",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 9, 23, 59, 59),
        )
        inside = TaskFactory(
            profile=profile,
            title="Inside",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 10, 12, 0, 0),
        )
        boundary = TaskFactory(
            profile=profile,
            title="Boundary",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 11, 0, 0, 0),
        )
        await db_session.commit()
        assert before.id and boundary.id
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}&include_closed=true"
            "&closed_from=2026-09-10T00:00:00&closed_to=2026-09-11T00:00:00"
        )

        titles = [t["title"] for t in response.json()["tasks"]]
        assert titles == ["Inside"]
        assert inside.id is not None

    async def test_closed_from_is_inclusive_at_the_lower_bound(
        self, client, db_session, login_as
    ):
        """>= at closed_from: a task closed at exactly that instant is IN."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        at_bound = TaskFactory(
            profile=profile,
            title="AtBound",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 10, 0, 0, 0),
        )
        await db_session.commit()
        assert at_bound.id is not None
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}&include_closed=true"
            "&closed_from=2026-09-10T00:00:00&closed_to=2026-09-11T00:00:00"
        )

        titles = [t["title"] for t in response.json()["tasks"]]
        assert titles == ["AtBound"]

    async def test_closed_range_without_include_closed_returns_nothing(
        self, client, db_session, login_as
    ):
        """closed_from/closed_to alone always return empty: include_closed
        defaults to False, which excludes every task that could match (only
        closed tasks ever have a closed_date). The same range with
        include_closed=true finds the task."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="ClosedToday",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 10, 12, 0, 0),
        )
        await db_session.commit()
        await login_as(user)

        without_include_closed = await client.get(
            f"/tasks/?profile_id={profile.id}"
            "&closed_from=2026-09-10T00:00:00&closed_to=2026-09-11T00:00:00"
        )
        with_include_closed = await client.get(
            f"/tasks/?profile_id={profile.id}&include_closed=true"
            "&closed_from=2026-09-10T00:00:00&closed_to=2026-09-11T00:00:00"
        )

        assert without_include_closed.json()["tasks"] == []
        titles = [t["title"] for t in with_include_closed.json()["tasks"]]
        assert titles == ["ClosedToday"]

    async def test_closed_from_alone_is_an_open_ended_tail(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="Old",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 1, 12, 0, 0),
        )
        TaskFactory(
            profile=profile,
            title="Recent",
            status=TaskStatus.DONE,
            closed_date=datetime(2026, 9, 20, 12, 0, 0),
        )
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}&include_closed=true"
            "&closed_from=2026-09-10T00:00:00"
        )

        titles = [t["title"] for t in response.json()["tasks"]]
        assert titles == ["Recent"]

    async def test_ordering_is_total_so_paging_cannot_drop_a_row(
        self, client, db_session, login_as
    ):
        """Three tasks identical on every sort key. Without an id tiebreaker
        the page boundary can duplicate one and drop another."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        stamp = datetime(2026, 9, 10, 12, 0, 0)
        for n in range(3):
            TaskFactory(
                profile=profile,
                title=f"Tie {n}",
                priority=1,
                due_date=None,
                created_date=stamp,
            )
        await db_session.commit()
        await login_as(user)

        first = await client.get(f"/tasks/?profile_id={profile.id}&limit=2&offset=0")
        second = await client.get(f"/tasks/?profile_id={profile.id}&limit=2&offset=2")

        ids = [t["id"] for t in first.json()["tasks"]] + [
            t["id"] for t in second.json()["tasks"]
        ]
        assert len(ids) == 3
        assert len(set(ids)) == 3


class TestCreatedDateRangeFilter:
    """Tests for the created_from/created_to query params on GET /tasks/."""

    async def test_returns_only_tasks_created_in_the_half_open_range(
        self, client, db_session, login_as
    ):
        """Half-open so consecutive days tile without overlapping: a task
        created exactly at `created_to` belongs to the next window."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="Before",
            created_date=datetime(2026, 9, 9, 23, 59, 59),
        )
        TaskFactory(
            profile=profile,
            title="AtLowerBound",
            created_date=datetime(2026, 9, 10, 0, 0, 0),
        )
        TaskFactory(
            profile=profile,
            title="Inside",
            created_date=datetime(2026, 9, 10, 12, 0, 0),
        )
        TaskFactory(
            profile=profile,
            title="Boundary",
            created_date=datetime(2026, 9, 11, 0, 0, 0),
        )
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}"
            "&created_from=2026-09-10T00:00:00&created_to=2026-09-11T00:00:00"
        )

        titles = sorted(t["title"] for t in response.json()["tasks"])
        assert titles == ["AtLowerBound", "Inside"]

    async def test_created_range_covers_tasks_already_closed(
        self, client, db_session, login_as
    ):
        """A task created and finished on the same day is still part of that
        day, so the window has to reach it - which needs include_closed."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="SameDay",
            status=TaskStatus.DONE,
            created_date=datetime(2026, 9, 10, 9, 0, 0),
            closed_date=datetime(2026, 9, 10, 17, 0, 0),
        )
        await db_session.commit()
        await login_as(user)

        window = (
            f"profile_id={profile.id}"
            "&created_from=2026-09-10T00:00:00&created_to=2026-09-11T00:00:00"
        )
        without = await client.get(f"/tasks/?{window}")
        assert without.json()["tasks"] == []

        with_closed = await client.get(f"/tasks/?{window}&include_closed=true")
        assert [t["title"] for t in with_closed.json()["tasks"]] == ["SameDay"]

    async def test_created_from_alone_is_an_open_ended_tail(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile, title="Old", created_date=datetime(2026, 9, 1, 0, 0, 0)
        )
        TaskFactory(
            profile=profile, title="New", created_date=datetime(2026, 9, 20, 0, 0, 0)
        )
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}&created_from=2026-09-10T00:00:00"
        )

        assert [t["title"] for t in response.json()["tasks"]] == ["New"]

    async def test_created_and_closed_windows_combine(
        self, client, db_session, login_as
    ):
        """Both filters apply together rather than one replacing the other."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="CreatedAndClosedSameDay",
            status=TaskStatus.DONE,
            created_date=datetime(2026, 9, 10, 9, 0, 0),
            closed_date=datetime(2026, 9, 10, 17, 0, 0),
        )
        TaskFactory(
            profile=profile,
            title="CreatedEarlierClosedToday",
            status=TaskStatus.DONE,
            created_date=datetime(2026, 9, 1, 9, 0, 0),
            closed_date=datetime(2026, 9, 10, 17, 0, 0),
        )
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            f"/tasks/?profile_id={profile.id}&include_closed=true"
            "&created_from=2026-09-10T00:00:00&created_to=2026-09-11T00:00:00"
            "&closed_from=2026-09-10T00:00:00&closed_to=2026-09-11T00:00:00"
        )

        titles = [t["title"] for t in response.json()["tasks"]]
        assert titles == ["CreatedAndClosedSameDay"]


class TestEditableClosedDate:
    async def _open_task(self, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()
        task = TaskFactory(profile=profile, title="Fix the tap")
        await db_session.commit()
        await login_as(user)
        return task

    async def test_closing_with_an_explicit_date_keeps_it(
        self, client, db_session, login_as
    ):
        """Close it today, dated last Tuesday, in one request."""
        task = await self._open_task(db_session, login_as)

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"status": TaskStatus.DONE, "closed_date": "2026-09-02T14:30:00"},
        )

        assert response.status_code == 200
        assert response.json()["closed_date"].startswith("2026-09-02T14:30:00")

    async def test_closing_without_one_still_stamps_now(
        self, client, db_session, login_as
    ):
        task = await self._open_task(db_session, login_as)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.DONE}
        )

        assert response.json()["closed_date"] is not None

    async def test_amending_the_date_on_an_already_closed_task(
        self, client, db_session, login_as
    ):
        task = await self._open_task(db_session, login_as)
        await client.patch(f"/tasks/{task.id}", json={"status": TaskStatus.DONE})

        response = await client.patch(
            f"/tasks/{task.id}", json={"closed_date": "2026-09-02T14:30:00"}
        )

        assert response.json()["closed_date"].startswith("2026-09-02T14:30:00")

    async def test_setting_it_on_an_open_task_is_422(
        self, client, db_session, login_as
    ):
        task = await self._open_task(db_session, login_as)

        response = await client.patch(
            f"/tasks/{task.id}", json={"closed_date": "2026-09-02T14:30:00"}
        )

        assert response.status_code == 422

    async def test_reopening_while_supplying_one_is_422(
        self, client, db_session, login_as
    ):
        task = await self._open_task(db_session, login_as)
        await client.patch(f"/tasks/{task.id}", json={"status": TaskStatus.DONE})

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"status": TaskStatus.OPEN, "closed_date": "2026-09-02T14:30:00"},
        )

        assert response.status_code == 422

    async def test_explicit_null_clears_the_date_on_a_closed_task(
        self, client, db_session, login_as
    ):
        """The column is nullable, so clearing it is allowed rather than a 422.
        Such a task then sorts first in the closed view (Postgres orders NULLs
        first under DESC) and matches no closed_from/closed_to range."""
        task = await self._open_task(db_session, login_as)
        await client.patch(f"/tasks/{task.id}", json={"status": TaskStatus.DONE})

        response = await client.patch(f"/tasks/{task.id}", json={"closed_date": None})

        assert response.status_code == 200
        assert response.json()["closed_date"] is None
        assert response.json()["status"] == TaskStatus.DONE

    async def test_a_future_closed_date_is_allowed(self, client, db_session, login_as):
        """The client sends its own local date, so a user east of the server
        legitimately closes a task on a date the server has not reached."""
        task = await self._open_task(db_session, login_as)
        ahead = (datetime.now() + timedelta(hours=20)).isoformat()

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.DONE, "closed_date": ahead}
        )

        assert response.status_code == 200
