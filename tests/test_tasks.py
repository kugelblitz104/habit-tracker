"""Tests for task management endpoints."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from habit_tracker.constants import TaskStatus
from habit_tracker.schemas.db_models import Task
from tests.factories import (
    AdminUserFactory,
    DoneTaskFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    UserFactory,
)


async def login_as(client, user):
    """Log in as the given user and attach the bearer token to the client."""
    login_response = await client.post(
        "/auth/login",
        data={"username": user.username, "password": "password123"},
    )
    token = login_response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})


class TestCreateTask:
    """Tests for POST /tasks/ endpoint."""

    async def test_create_task_quick_capture(self, client, db_session, setup_factories):
        """Only profile_id and title are required; everything else defaults."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/tasks/", json={"profile_id": profile.id, "title": "Buy milk"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Buy milk"
        assert data["profile_id"] == profile.id
        assert data["status"] == TaskStatus.OPEN
        assert data["priority"] == 0
        assert data["band"] == "whenever"
        assert data["project_id"] is None
        assert data["due_date"] is None
        assert data["closed_date"] is None

    async def test_create_task_all_fields(self, client, db_session, setup_factories):
        """Create task with a full payload and get it echoed back."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        due = date.today() + timedelta(days=1)

        await login_as(client, user)

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
        assert data["band"] == "now"  # priority 3

    async def test_create_task_with_scheduled_date_time(
        self, client, db_session, setup_factories
    ):
        """scheduled_date/scheduled_time persist and round-trip in TaskRead."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(client, user)

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
        # A scheduled date 3 days out bands the task as "soon" (no due date)
        assert data["band"] == "soon"

        # Round-trips on a fresh GET too
        response = await client.get(f"/tasks/{data['id']}")
        assert response.status_code == 200
        got = response.json()
        assert got["scheduled_date"] == scheduled.isoformat()
        assert got["scheduled_time"] == "09:15:00"

    async def test_create_non_scheduled_task_clears_scheduled_data(
        self, client, db_session, setup_factories
    ):
        """A non-SCHEDULED status forces scheduled_date/time null even if sent."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(client, user)

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
        # No due date + priority 0 + cleared scheduled date -> whenever
        assert data["band"] == "whenever"

        # Confirm it was persisted as null, not just scrubbed in the response
        db_task = await db_session.get(Task, data["id"])
        await db_session.refresh(db_task)
        assert db_task.scheduled_date is None
        assert db_task.scheduled_time is None

    async def test_create_scheduled_task_keeps_scheduled_data(
        self, client, db_session, setup_factories
    ):
        """A SCHEDULED status keeps supplied scheduled_date/time."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=3)

        await login_as(client, user)

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
        self, client, db_session, setup_factories
    ):
        """A project in a different profile is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project = ProjectFactory(profile=other_profile)
        await db_session.commit()

        await login_as(client, user)

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
        self, client, db_session, setup_factories
    ):
        """Foreign profile is 403; non-existent profile is 404."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/tasks/", json={"profile_id": foreign.id, "title": "Nope"}
        )
        assert response.status_code == 403

        response = await client.post(
            "/tasks/", json={"profile_id": 99999, "title": "Nope"}
        )
        assert response.status_code == 404

    async def test_create_task_done_stamps_closed_date(
        self, client, db_session, setup_factories
    ):
        """Creating a task already DONE stamps its closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

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
        assert data["band"] == "hidden"


class TestListTasks:
    """Tests for GET /tasks/ endpoint."""

    async def test_list_tasks_excludes_closed_by_default(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.get("/tasks/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {t["id"] for t in data["tasks"]}
        assert ids == {open_task.id, blocked_task.id}

    async def test_list_tasks_include_closed(self, client, db_session, setup_factories):
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

        await login_as(client, user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "include_closed": True}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 3

    async def test_list_tasks_status_filter_includes_done(
        self, client, db_session, setup_factories
    ):
        """An explicit status filter works even for DONE."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(profile=profile, status=TaskStatus.OPEN)
        done = DoneTaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/tasks/",
            params={"profile_id": profile.id, "status": TaskStatus.DONE.value},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["id"] == done.id
        assert data["tasks"][0]["band"] == "hidden"

    async def test_list_tasks_band_membership(
        self, client, db_session, setup_factories
    ):
        """Band filter returns tasks whose computed band matches."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        today = date.today()
        overdue = TaskFactory(profile=profile, due_date=today - timedelta(days=1))
        due_today = TaskFactory(profile=profile, due_date=today)
        prio3 = TaskFactory(profile=profile, priority=3)
        due_soon = TaskFactory(profile=profile, due_date=today + timedelta(days=3))
        prio2 = TaskFactory(profile=profile, priority=2)
        due_later = TaskFactory(profile=profile, due_date=today + timedelta(days=10))
        prio1 = TaskFactory(profile=profile, priority=1)
        plain = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "band": "now"}
        )
        assert response.status_code == 200
        assert {t["id"] for t in response.json()["tasks"]} == {
            overdue.id,
            due_today.id,
            prio3.id,
        }

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "band": "soon"}
        )
        assert response.status_code == 200
        assert {t["id"] for t in response.json()["tasks"]} == {due_soon.id, prio2.id}

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "band": "whenever"}
        )
        assert response.status_code == 200
        assert {t["id"] for t in response.json()["tasks"]} == {
            due_later.id,
            prio1.id,
            plain.id,
        }

    async def test_list_tasks_invalid_band(self, client, db_session, setup_factories):
        """An invalid band value is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "band": "urgent"}
        )
        assert response.status_code == 422

    async def test_list_tasks_completed_view_ordering(
        self, client, db_session, setup_factories
    ):
        """band=hidden&include_closed=true orders by closed_date descending."""
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
        TaskFactory(profile=profile)  # open task stays out of the hidden band
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/tasks/",
            params={
                "profile_id": profile.id,
                "band": "hidden",
                "include_closed": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert [t["id"] for t in data["tasks"]] == [newest.id, middle.id, oldest.id]

    async def test_list_tasks_active_ordering(
        self, client, db_session, setup_factories
    ):
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

        await login_as(client, user)

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

    async def test_list_tasks_pagination_after_band_filter(
        self, client, db_session, setup_factories
    ):
        """limit/offset apply to the band-filtered list; total matches it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        today = date.today()
        # Five overdue tasks - all band "now" - with ascending due dates
        now_tasks = [
            TaskFactory(profile=profile, due_date=today - timedelta(days=5 - i))
            for i in range(5)
        ]
        # Two "whenever" tasks that must not affect the paging or the total
        TaskFactory(profile=profile)
        TaskFactory(profile=profile, priority=1)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/tasks/",
            params={"profile_id": profile.id, "band": "now", "limit": 2, "offset": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 2
        # Ordered by due date ascending, the slice skips the two most overdue
        assert [t["id"] for t in data["tasks"]] == [now_tasks[2].id, now_tasks[3].id]

    async def test_list_tasks_project_filter(self, client, db_session, setup_factories):
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

        await login_as(client, user)

        response = await client.get(
            "/tasks/", params={"profile_id": profile.id, "project_id": project.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["id"] == in_project.id

    async def test_list_tasks_foreign_or_missing_profile(
        self, client, db_session, setup_factories
    ):
        """Foreign profile is 403; non-existent profile is 404."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(client, user)

        response = await client.get("/tasks/", params={"profile_id": foreign.id})
        assert response.status_code == 403

        response = await client.get("/tasks/", params={"profile_id": 99999})
        assert response.status_code == 404


class TestGetTask:
    """Tests for GET /tasks/{task_id} endpoint."""

    async def test_get_own_task(self, client, db_session, setup_factories):
        """User can retrieve their task, including its computed band."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=3)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task.id
        assert data["band"] == "now"

    async def test_get_task_as_admin(self, client, db_session, setup_factories):
        """Admin can access any task."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, admin)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 200

    async def test_get_other_user_task(self, client, db_session, setup_factories):
        """User cannot access a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(f"/tasks/{task.id}")
        assert response.status_code == 403

    async def test_get_nonexistent_task(self, client, db_session, setup_factories):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.get("/tasks/99999")
        assert response.status_code == 404


class TestPatchTask:
    """Tests for PATCH /tasks/{task_id} endpoint."""

    async def test_patch_task_priority_flips_band(
        self, client, db_session, setup_factories
    ):
        """Raising priority to 3 moves the task from whenever to now."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(f"/tasks/{task.id}", json={"priority": 3})
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == 3
        assert data["band"] == "now"

    async def test_patch_task_scheduled_date_moves_band(
        self, client, db_session, setup_factories
    ):
        """Setting a near-future scheduled_date moves the task into 'soon'."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0)  # starts "whenever"
        await db_session.commit()

        await login_as(client, user)

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
        assert data["band"] == "soon"

    async def test_patch_task_clear_scheduled_date(
        self, client, db_session, setup_factories
    ):
        """scheduled_date is nullable - PATCH scheduled_date=null clears it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        scheduled = date.today() + timedelta(days=2)
        task = TaskFactory(
            profile=profile, priority=0, scheduled_date=scheduled
        )
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"scheduled_date": None}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scheduled_date"] is None
        # With no due or scheduled date and priority 0, band falls back to whenever
        assert data["band"] == "whenever"

    async def test_patch_status_away_from_scheduled_clears_scheduled_data(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        # Only the status changes - the scheduled fields are NOT part of the body
        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.OPEN.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.OPEN
        assert data["scheduled_date"] is None
        assert data["scheduled_time"] is None
        # Banding reflects the cleared date: soon -> whenever
        assert data["band"] == "whenever"

        # Persisted as null, not just scrubbed in the response
        db_task = await db_session.get(Task, task.id)
        await db_session.refresh(db_task)
        assert db_task.scheduled_date is None
        assert db_task.scheduled_time is None

    async def test_patch_scheduled_task_keeps_scheduled_date(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        new_scheduled = date.today() + timedelta(days=2)
        response = await client.patch(
            f"/tasks/{task.id}",
            json={"scheduled_date": new_scheduled.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.SCHEDULED
        assert data["scheduled_date"] == new_scheduled.isoformat()
        assert data["band"] == "soon"

    async def test_patch_non_scheduled_task_to_scheduled_keeps_scheduled_date(
        self, client, db_session, setup_factories
    ):
        """Setting status to SCHEDULED + scheduled_date in one PATCH keeps it."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, priority=0, status=TaskStatus.OPEN)
        await db_session.commit()

        await login_as(client, user)

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
        assert data["band"] == "soon"

    async def test_patch_task_done_sets_closed_date(
        self, client, db_session, setup_factories
    ):
        """Setting status to DONE stamps closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile, status=TaskStatus.OPEN)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.DONE.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.DONE
        assert data["closed_date"] is not None
        assert data["band"] == "hidden"

    async def test_patch_task_done_to_cancelled_preserves_closed_date(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.CANCELLED.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.CANCELLED
        assert data["closed_date"] == "2026-01-05T12:00:00"

    async def test_patch_task_reopen_clears_closed_date(
        self, client, db_session, setup_factories
    ):
        """Reopening a closed task clears its closed_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = DoneTaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"status": TaskStatus.OPEN.value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.OPEN
        assert data["closed_date"] is None

    async def test_patch_task_block_reason_set_and_clear(
        self, client, db_session, setup_factories
    ):
        """block_reason can be set and cleared."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

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
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"project_id": project.id}
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == project.id

    async def test_patch_task_move_to_project_in_other_profile(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"project_id": project.id}
        )
        assert response.status_code == 400

    async def test_patch_task_profile_move_without_project(
        self, client, db_session, setup_factories
    ):
        """A task with no project can move to another of the user's profiles."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 200
        assert response.json()["profile_id"] == other_profile.id

    async def test_patch_task_profile_move_with_project_in_old_profile(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 400

    async def test_patch_task_profile_move_to_other_user_profile(
        self, client, db_session, setup_factories
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

        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"profile_id": foreign.id}
        )
        assert response.status_code == 400

    async def test_patch_task_null_title(self, client, db_session, setup_factories):
        """An explicit null for the non-nullable title is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(f"/tasks/{task.id}", json={"title": None})
        assert response.status_code == 422

    async def test_patch_task_null_profile_id(
        self, client, db_session, setup_factories
    ):
        """An explicit null for the non-nullable profile_id is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(f"/tasks/{task.id}", json={"profile_id": None})
        assert response.status_code == 422

    async def test_patch_other_user_task(self, client, db_session, setup_factories):
        """User cannot patch a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(f"/tasks/{task.id}", json={"title": "Hax"})
        assert response.status_code == 403

    async def test_patch_nonexistent_task(self, client, db_session, setup_factories):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch("/tasks/99999", json={"title": "Ghost"})
        assert response.status_code == 404


class TestDeleteTask:
    """Tests for DELETE /tasks/{task_id} endpoint."""

    async def test_delete_own_task(self, client, db_session, setup_factories):
        """User can delete their task."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()
        task_id = task.id

        await login_as(client, user)

        response = await client.delete(f"/tasks/{task_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Task).filter(Task.id == task_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_task(self, client, db_session, setup_factories):
        """User cannot delete a task in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        task = TaskFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.delete(f"/tasks/{task.id}")
        assert response.status_code == 403

    async def test_delete_nonexistent_task(self, client, db_session, setup_factories):
        """Return 404 for non-existent task."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.delete("/tasks/99999")
        assert response.status_code == 404
