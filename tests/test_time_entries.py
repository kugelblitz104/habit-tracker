"""Tests for time-tracking endpoints (pomodoro + stopwatch time entries)."""

from datetime import datetime, timedelta

from sqlalchemy import select

from habit_tracker.constants import TimeEntryKind
from habit_tracker.schemas.db_models import TimeEntry
from tests.factories import (
    ProfileFactory,
    ProjectFactory,
    RunningTimeEntryFactory,
    TaskFactory,
    TimeEntryFactory,
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


class TestListTimeEntries:
    """Tests for GET /time-entries/ endpoint."""

    async def test_requires_profile_id(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get("/time-entries/")
        assert response.status_code == 422

    async def test_unknown_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get("/time-entries/", params={"profile_id": 99999})
        assert response.status_code == 404

    async def test_foreign_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/", params={"profile_id": other.profiles[0].id}
        )
        assert response.status_code == 403

    async def test_empty_list(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/", params={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["time_entries"] == []

    async def test_ordered_started_at_desc(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        base = datetime(2026, 7, 1, 9, 0, 0)
        older = TimeEntryFactory(profile=profile, started_at=base)
        newer = TimeEntryFactory(
            profile=profile, started_at=base + timedelta(hours=2)
        )
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        ids = [e["id"] for e in response.json()["time_entries"]]
        assert ids == [newer.id, older.id]

    async def test_filter_by_task(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        task = TaskFactory(profile=profile)
        await db_session.flush()
        matching = TimeEntryFactory(profile=profile, task=task)
        TimeEntryFactory(profile=profile, task=None)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/",
            params={"profile_id": profile.id, "task_id": task.id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["time_entries"][0]["id"] == matching.id

    async def test_filter_by_project(self, client, db_session, setup_factories):
        """project_id returns task-attached (via task's project) + adhoc entries."""
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        other_project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile, project=project)
        other_task = TaskFactory(profile=profile, project=other_project)
        await db_session.flush()
        via_task = TimeEntryFactory(profile=profile, task=task)
        adhoc = TimeEntryFactory(profile=profile, task=None, project_id=project.id)
        # entries that should be excluded
        TimeEntryFactory(profile=profile, task=other_task)
        TimeEntryFactory(profile=profile, task=None)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/",
            params={"profile_id": profile.id, "project_id": project.id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        ids = {e["id"] for e in body["time_entries"]}
        assert ids == {via_task.id, adhoc.id}

    async def test_filter_by_kind(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        pomodoro = TimeEntryFactory(profile=profile, kind=TimeEntryKind.POMODORO)
        TimeEntryFactory(profile=profile, kind=TimeEntryKind.STOPWATCH)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/",
            params={"profile_id": profile.id, "kind": TimeEntryKind.POMODORO.value},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["time_entries"][0]["id"] == pomodoro.id

    async def test_filter_by_running(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        running = RunningTimeEntryFactory(profile=profile)
        TimeEntryFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/", params={"profile_id": profile.id, "running": "true"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["time_entries"][0]["id"] == running.id
        assert body["time_entries"][0]["is_running"] is True

    async def test_invalid_kind(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/",
            params={"profile_id": user.profiles[0].id, "kind": 99},
        )
        assert response.status_code == 422


class TestCreateTimeEntry:
    """Tests for POST /time-entries/ endpoint."""

    async def test_start_running_timer(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/", json={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["is_running"] is True
        assert body["ended_at"] is None
        assert body["duration_seconds"] is None
        assert body["started_at"] is not None
        assert body["kind"] == TimeEntryKind.STOPWATCH.value

    async def test_start_with_task(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        task = TaskFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": profile.id,
                "task_id": task.id,
                "kind": TimeEntryKind.POMODORO.value,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["task_id"] == task.id
        assert body["kind"] == TimeEntryKind.POMODORO.value

    async def test_second_running_timer_conflicts(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = user.profiles[0]
        RunningTimeEntryFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/", json={"profile_id": profile.id}
        )
        assert response.status_code == 409

    async def test_log_completed_entry_computes_duration(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        start = datetime(2026, 7, 1, 9, 0, 0)
        end = start + timedelta(minutes=25)
        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": user.profiles[0].id,
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["is_running"] is False
        assert body["duration_seconds"] == 25 * 60

    async def test_completed_entry_ignores_running_guard(
        self, client, db_session, setup_factories
    ):
        """Logging a completed entry is allowed even while a timer runs."""
        user = UserFactory()
        profile = user.profiles[0]
        RunningTimeEntryFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        start = datetime(2026, 7, 1, 9, 0, 0)
        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": profile.id,
                "started_at": start.isoformat(),
                "ended_at": (start + timedelta(minutes=5)).isoformat(),
            },
        )
        assert response.status_code == 201

    async def test_ended_before_started(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        start = datetime(2026, 7, 1, 9, 0, 0)
        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": user.profiles[0].id,
                "started_at": start.isoformat(),
                "ended_at": (start - timedelta(minutes=5)).isoformat(),
            },
        )
        assert response.status_code == 400

    async def test_task_in_other_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        other_profile = ProfileFactory(user=user)
        task = TaskFactory(profile=other_profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={"profile_id": profile.id, "task_id": task.id},
        )
        assert response.status_code == 400

    async def test_foreign_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/", json={"profile_id": other.profiles[0].id}
        )
        assert response.status_code == 403

    async def test_invalid_kind(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={"profile_id": user.profiles[0].id, "kind": 99},
        )
        assert response.status_code == 422


class TestActiveTimeEntry:
    """Tests for GET /time-entries/active endpoint."""

    async def test_returns_running_entry(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        running = RunningTimeEntryFactory(profile=profile)
        TimeEntryFactory(profile=profile)  # completed - not returned
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/active", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body is not None
        assert body["id"] == running.id
        assert body["is_running"] is True

    async def test_returns_null_when_none(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        TimeEntryFactory(profile=profile)  # completed only
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/active", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json() is None

    async def test_foreign_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/active", params={"profile_id": other.profiles[0].id}
        )
        assert response.status_code == 403


class TestStopTimeEntry:
    """Tests for POST /time-entries/{id}/stop endpoint."""

    async def test_stop_running(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        entry = RunningTimeEntryFactory(
            profile=profile, started_at=datetime.now() - timedelta(minutes=10)
        )
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(f"/time-entries/{entry.id}/stop")
        assert response.status_code == 200
        body = response.json()
        assert body["is_running"] is False
        assert body["ended_at"] is not None
        # ~10 minutes elapsed
        assert body["duration_seconds"] >= 60 * 9

    async def test_stop_already_stopped(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        entry = TimeEntryFactory(profile=profile)  # completed
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(f"/time-entries/{entry.id}/stop")
        assert response.status_code == 400

    async def test_stop_unknown(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post("/time-entries/99999/stop")
        assert response.status_code == 404

    async def test_stop_foreign(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        entry = RunningTimeEntryFactory(profile=other.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(f"/time-entries/{entry.id}/stop")
        assert response.status_code == 403


class TestTimeEntrySummary:
    """Tests for GET /time-entries/summary endpoint."""

    async def test_aggregates_per_task(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        task_a = TaskFactory(profile=profile)
        task_b = TaskFactory(profile=profile)
        await db_session.flush()
        TimeEntryFactory(profile=profile, task=task_a, duration_seconds=100)
        TimeEntryFactory(profile=profile, task=task_a, duration_seconds=200)
        TimeEntryFactory(profile=profile, task=task_b, duration_seconds=50)
        # running entry (no duration) must be excluded
        RunningTimeEntryFactory(profile=profile, task=task_a)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/summary", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_seconds"] == 350
        per_task = {item["task_id"]: item for item in body["per_task"]}
        assert per_task[task_a.id]["total_seconds"] == 300
        assert per_task[task_a.id]["entry_count"] == 2
        assert per_task[task_b.id]["total_seconds"] == 50

    async def test_untethered_bucket(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        TimeEntryFactory(profile=profile, task=None, duration_seconds=120)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/summary", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_seconds"] == 120
        assert body["per_task"][0]["task_id"] is None
        assert body["per_task"][0]["total_seconds"] == 120

    async def test_foreign_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/summary",
            params={"profile_id": other.profiles[0].id},
        )
        assert response.status_code == 403


class TestReadTimeEntry:
    """Tests for GET /time-entries/{id} endpoint."""

    async def test_read(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(f"/time-entries/{entry.id}")
        assert response.status_code == 200
        assert response.json()["id"] == entry.id

    async def test_read_unknown(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.get("/time-entries/99999")
        assert response.status_code == 404

    async def test_read_foreign(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        entry = TimeEntryFactory(profile=other.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(f"/time-entries/{entry.id}")
        assert response.status_code == 403


class TestPatchTimeEntry:
    """Tests for PATCH /time-entries/{id} endpoint."""

    async def test_update_note(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0], note=None)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"note": "focus block"}
        )
        assert response.status_code == 200
        assert response.json()["note"] == "focus block"

    async def test_attach_and_detach_task(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        task = TaskFactory(profile=profile)
        entry = TimeEntryFactory(profile=profile, task=None)
        await db_session.commit()
        await login_as(client, user)

        attach = await client.patch(
            f"/time-entries/{entry.id}", json={"task_id": task.id}
        )
        assert attach.status_code == 200
        assert attach.json()["task_id"] == task.id

        detach = await client.patch(
            f"/time-entries/{entry.id}", json={"task_id": None}
        )
        assert detach.status_code == 200
        assert detach.json()["task_id"] is None

    async def test_task_in_other_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        other_profile = ProfileFactory(user=user)
        task = TaskFactory(profile=other_profile)
        entry = TimeEntryFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"task_id": task.id}
        )
        assert response.status_code == 400

    async def test_change_ended_at_recomputes_duration(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = user.profiles[0]
        start = datetime(2026, 7, 1, 9, 0, 0)
        entry = TimeEntryFactory(
            profile=profile,
            started_at=start,
            ended_at=start + timedelta(minutes=10),
            duration_seconds=600,
        )
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}",
            json={"ended_at": (start + timedelta(minutes=30)).isoformat()},
        )
        assert response.status_code == 200
        assert response.json()["duration_seconds"] == 30 * 60

    async def test_reopen_makes_running(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"ended_at": None}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_running"] is True
        assert body["duration_seconds"] is None

    async def test_reopen_conflicts_with_running(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = user.profiles[0]
        RunningTimeEntryFactory(profile=profile)
        entry = TimeEntryFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"ended_at": None}
        )
        assert response.status_code == 409

    async def test_ended_before_started(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        start = datetime(2026, 7, 1, 9, 0, 0)
        entry = TimeEntryFactory(
            profile=profile,
            started_at=start,
            ended_at=start + timedelta(minutes=10),
            duration_seconds=600,
        )
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}",
            json={"ended_at": (start - timedelta(minutes=1)).isoformat()},
        )
        assert response.status_code == 400

    async def test_reject_null_kind(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"kind": None}
        )
        assert response.status_code == 422

    async def test_foreign(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        entry = TimeEntryFactory(profile=other.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"note": "x"}
        )
        assert response.status_code == 403


class TestDeleteTimeEntry:
    """Tests for DELETE /time-entries/{id} endpoint."""

    async def test_delete(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.delete(f"/time-entries/{entry.id}")
        assert response.status_code == 200

        remaining = await db_session.execute(
            select(TimeEntry).filter(TimeEntry.id == entry.id)
        )
        assert remaining.scalar_one_or_none() is None

    async def test_delete_unknown(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.delete("/time-entries/99999")
        assert response.status_code == 404

    async def test_delete_foreign(self, client, db_session, setup_factories):
        user = UserFactory()
        other = UserFactory()
        entry = TimeEntryFactory(profile=other.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.delete(f"/time-entries/{entry.id}")
        assert response.status_code == 403


class TestTimeEntryCascade:
    """Deleting a task or profile removes its time entries (DB cascade)."""

    async def test_deleting_task_deletes_entries(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = user.profiles[0]
        task = TaskFactory(profile=profile)
        await db_session.flush()
        entry = TimeEntryFactory(profile=profile, task=task)
        await db_session.commit()
        await login_as(client, user)

        response = await client.delete(f"/tasks/{task.id}")
        assert response.status_code == 200

        remaining = await db_session.execute(
            select(TimeEntry).filter(TimeEntry.id == entry.id)
        )
        assert remaining.scalar_one_or_none() is None


class TestTimeEntryProjectAndLabel:
    """Adhoc project attachment + label on time entries."""

    async def test_create_adhoc_project_entry(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": profile.id,
                "project_id": project.id,
                "label": "Roadmap planning",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["project_id"] == project.id
        assert body["task_id"] is None
        assert body["label"] == "Roadmap planning"

    async def test_task_wins_over_project(self, client, db_session, setup_factories):
        """When both are supplied, the task attaches and project is dropped."""
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={
                "profile_id": profile.id,
                "task_id": task.id,
                "project_id": project.id,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["task_id"] == task.id
        assert body["project_id"] is None

    async def test_project_in_other_profile(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        other_profile = ProfileFactory(user=user)
        project = ProjectFactory(profile=other_profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={"profile_id": profile.id, "project_id": project.id},
        )
        assert response.status_code == 400

    async def test_blank_label_normalized_to_null(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/time-entries/",
            json={"profile_id": user.profiles[0].id, "label": "   "},
        )
        assert response.status_code == 201
        assert response.json()["label"] is None

    async def test_patch_label(self, client, db_session, setup_factories):
        user = UserFactory()
        entry = TimeEntryFactory(profile=user.profiles[0], label=None)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"label": "Standup"}
        )
        assert response.status_code == 200
        assert response.json()["label"] == "Standup"

    async def test_patch_task_clears_project(self, client, db_session, setup_factories):
        """Attaching a task to an adhoc project entry drops the project."""
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile)
        entry = TimeEntryFactory(profile=profile, project_id=project.id)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"task_id": task.id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task.id
        assert body["project_id"] is None

    async def test_patch_attach_project_to_adhoc(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        entry = TimeEntryFactory(profile=profile, task=None)
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/time-entries/{entry.id}", json={"project_id": project.id}
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == project.id


class TestTimeEntrySummaryPerProject:
    """Per-project aggregation resolves task-attached and adhoc entries."""

    async def test_per_project_rollup(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile, project=project)
        await db_session.flush()
        # task-attached entry -> counts toward the task's project
        TimeEntryFactory(profile=profile, task=task, duration_seconds=100)
        # adhoc entry attached directly to the same project
        TimeEntryFactory(
            profile=profile, task=None, project_id=project.id, duration_seconds=50
        )
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/summary", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        body = response.json()
        per_project = {item["project_id"]: item for item in body["per_project"]}
        assert per_project[project.id]["total_seconds"] == 150
        assert per_project[project.id]["entry_count"] == 2

    async def test_per_project_null_bucket(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = user.profiles[0]
        task = TaskFactory(profile=profile, project=None)
        await db_session.flush()
        TimeEntryFactory(profile=profile, task=task, duration_seconds=30)
        await db_session.commit()
        await login_as(client, user)

        response = await client.get(
            "/time-entries/summary", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        per_project = {item["project_id"]: item for item in response.json()["per_project"]}
        assert per_project[None]["total_seconds"] == 30


class TestTaskEstimatedEffort:
    """Task gains an estimated_effort field (minutes)."""

    async def test_create_with_estimated_effort(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Write report",
                "estimated_effort": 90,
            },
        )
        assert response.status_code == 201
        assert response.json()["estimated_effort"] == 90

    async def test_default_is_null(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/tasks/",
            json={"profile_id": user.profiles[0].id, "title": "No estimate"},
        )
        assert response.status_code == 201
        assert response.json()["estimated_effort"] is None

    async def test_patch_estimated_effort(self, client, db_session, setup_factories):
        user = UserFactory()
        task = TaskFactory(profile=user.profiles[0])
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/tasks/{task.id}", json={"estimated_effort": 45}
        )
        assert response.status_code == 200
        assert response.json()["estimated_effort"] == 45

    async def test_negative_rejected(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/tasks/",
            json={
                "profile_id": user.profiles[0].id,
                "title": "Bad estimate",
                "estimated_effort": -5,
            },
        )
        assert response.status_code == 422


class TestProfilePomodoroSettings:
    """Profiles carry per-profile pomodoro defaults."""

    async def test_defaults(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/profiles/", json={"name": "Focus"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["pomodoro_work_minutes"] == 25
        assert body["pomodoro_break_minutes"] == 5
        assert body["pomodoro_long_break_minutes"] == 15
        assert body["pomodoro_cycles"] == 4

    async def test_create_custom(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/profiles/",
            json={
                "name": "Deep Work",
                "pomodoro_work_minutes": 50,
                "pomodoro_break_minutes": 10,
                "pomodoro_long_break_minutes": 30,
                "pomodoro_cycles": 3,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["pomodoro_work_minutes"] == 50
        assert body["pomodoro_cycles"] == 3

    async def test_patch(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/profiles/{user.profiles[0].id}",
            json={"pomodoro_work_minutes": 45},
        )
        assert response.status_code == 200
        assert response.json()["pomodoro_work_minutes"] == 45

    async def test_zero_rejected(self, client, db_session, setup_factories):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/profiles/",
            json={"name": "Bad", "pomodoro_work_minutes": 0},
        )
        assert response.status_code == 422

    async def test_show_estimated_effort_defaults_off(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.post("/profiles/", json={"name": "Estimator"})
        assert response.status_code == 201
        assert response.json()["show_estimated_effort"] is False

    async def test_toggle_show_estimated_effort(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/profiles/{user.profiles[0].id}",
            json={"show_estimated_effort": True},
        )
        assert response.status_code == 200
        assert response.json()["show_estimated_effort"] is True
