"""Tests for the full-profile backup export/import (JSON round-trip)."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from habit_tracker.constants import TaskStatus, TimeEntryKind, TrackerStatus
from habit_tracker.models.backup import IntegrationConnectionBackup, ProfileBackup
from habit_tracker.schemas.db_models import (
    Countdown,
    Habit,
    IntegrationConnection,
    Profile,
    Task,
    TimeEntry,
    Tracker,
)
from habit_tracker.services.profile_backup import build_profile_backup
from tests.factories import (
    CalendarConnectionFactory,
    CountdownFactory,
    HabitFactory,
    IntegrationConnectionFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    TimeEntryFactory,
    TrackerFactory,
    UserFactory,
)


class TestBackupModelShape:
    """The backup document never carries secrets or internal cache state."""

    def test_integration_backup_has_no_token_field(self):
        assert "encrypted_token" not in IntegrationConnectionBackup.model_fields
        assert "has_token" in IntegrationConnectionBackup.model_fields

    def test_calendar_backup_excludes_cache_fields(self):
        from habit_tracker.models.backup import CalendarConnectionBackup

        for cache_field in ("cached_ics", "etag", "last_fetched_at", "last_error"):
            assert cache_field not in CalendarConnectionBackup.model_fields


class TestBuildProfileBackup:
    """Unit tests for the pure builder (no HTTP, no database)."""

    def test_builds_document_with_defaults_and_refs(self):
        profile = Profile(
            name="Work",
            color_start="#e0763f",
            color_end="#c14e6a",
            habits_enabled=True,
            countdowns_enabled=True,
            insights_enabled=True,
            calendar_enabled=True,
            publish_to_azure=False,
            default_landing="today",
            week_start_monday=False,
            use_habit_color_accent=False,
            show_estimated_effort=False,
            pomodoro_work_minutes=50,
            pomodoro_break_minutes=10,
            pomodoro_long_break_minutes=20,
            pomodoro_cycles=3,
        )
        task = Task(
            title="Ship it",
            status=TaskStatus.OPEN.value,
            priority=0,
            sort_order=0,
        )
        task.id = 42
        task.project_id = 7
        task.parent_id = None
        integration = IntegrationConnection(
            provider="azure_devops",
            name="ADO",
            encrypted_token="ciphertext-here",
            enabled=True,
        )
        integration.id = 5

        backup = build_profile_backup(
            profile=profile,
            projects=[],
            tasks=[task],
            countdowns=[],
            time_entries=[],
            habits=[],
            trackers=[],
            calendar_connections=[],
            integration_connections=[integration],
            exported_at=datetime(2026, 7, 24, 12, 0),
        )

        assert backup.format == "habit-tracker-profile-backup"
        assert backup.version == 1
        assert backup.profile.name == "Work"
        assert backup.profile.week_start_monday is False
        assert backup.profile.pomodoro_work_minutes == 50
        assert backup.tasks[0].id == 42
        assert backup.tasks[0].project_id == 7
        # The token is recorded as present but never serialized.
        assert backup.integration_connections[0].has_token is True
        assert "encrypted_token" not in backup.integration_connections[0].model_dump()


async def _seed_full_profile(db_session, user):
    """Create one profile with at least one of every entity type, wired up."""
    profile = ProfileFactory(
        user=user, name="Work", week_start_monday=False, pomodoro_work_minutes=50
    )
    await db_session.commit()

    project = ProjectFactory(profile=profile, name="Website")
    await db_session.commit()

    parent = TaskFactory(
        profile=profile, title="Parent task", project=project, priority=2
    )
    await db_session.commit()
    subtask = TaskFactory(
        profile=profile, title="Subtask", parent_id=parent.id, project=project
    )
    await db_session.commit()

    CountdownFactory(
        profile=profile,
        task=parent,
        title="Launch day",
        target_date=date.today() + timedelta(days=10),
        repeat="none",
    )

    # A task-attached entry and an adhoc project entry.
    TimeEntryFactory(
        profile=profile,
        task=parent,
        kind=TimeEntryKind.STOPWATCH,
        duration_seconds=1800,
        label="Focus",
    )
    adhoc = TimeEntry(
        profile_id=profile.id,
        project_id=project.id,
        kind=TimeEntryKind.STOPWATCH.value,
        started_at=datetime.now(),
        ended_at=datetime.now(),
        duration_seconds=600,
        label="Adhoc",
    )
    db_session.add(adhoc)

    habit = HabitFactory(user=user, profile=profile, name="Read")
    await db_session.commit()
    TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.COMPLETED)

    CalendarConnectionFactory(profile=profile, name="Team cal")
    IntegrationConnectionFactory(profile=profile, name="My ADO", provider="github")
    await db_session.commit()

    return profile, project, parent, subtask, habit


class TestExport:
    async def test_export_contains_every_entity_and_no_token(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile, *_ = await _seed_full_profile(db_session, user)

        await login_as(user)
        resp = await client.get(f"/backup/profiles/{profile.id}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["format"] == "habit-tracker-profile-backup"
        assert body["profile"]["name"] == "Work"
        assert len(body["projects"]) == 1
        assert len(body["tasks"]) == 2
        assert len(body["countdowns"]) == 1
        assert len(body["time_entries"]) == 2
        assert len(body["habits"]) == 1
        assert len(body["trackers"]) == 1
        assert len(body["calendar_connections"]) == 1
        assert len(body["integration_connections"]) == 1
        # The PAT is never serialized, but its presence is recorded.
        conn = body["integration_connections"][0]
        assert "encrypted_token" not in conn
        assert conn["has_token"] is True
        # ICS cache is not exported.
        assert "cached_ics" not in body["calendar_connections"][0]

    async def test_export_unknown_profile_returns_404(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        resp = await client.get("/backup/profiles/999999")
        assert resp.status_code == 404

    async def test_export_other_users_profile_forbidden(
        self, client, db_session, login_as
    ):
        owner = UserFactory()
        intruder = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=owner, name="Private")
        await db_session.commit()

        await login_as(intruder)
        resp = await client.get(f"/backup/profiles/{profile.id}")
        assert resp.status_code == 403


class TestImportRoundTrip:
    async def test_roundtrip_recreates_entities_with_remapped_relationships(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        src_profile, *_ = await _seed_full_profile(db_session, user)

        await login_as(user)
        export = (await client.get(f"/backup/profiles/{src_profile.id}")).json()

        resp = await client.post("/backup/profiles", json=export)
        assert resp.status_code == 201
        summary = resp.json()

        # Imported as a new profile, name suffixed to dodge the unique collision.
        new_profile_id = summary["profile_id"]
        assert new_profile_id != src_profile.id
        assert summary["profile_name"] == "Work (imported)"
        assert summary["projects_imported"] == 1
        assert summary["tasks_imported"] == 1
        assert summary["subtasks_imported"] == 1
        assert summary["countdowns_imported"] == 1
        assert summary["time_entries_imported"] == 2
        assert summary["habits_imported"] == 1
        assert summary["trackers_imported"] == 1
        assert summary["calendar_connections_imported"] == 1
        assert summary["integration_connections_imported"] == 1
        # The tokenless integration is flagged for re-auth.
        assert any("re-enter" in w for w in summary["warnings"])

        # Profile settings copied.
        new_profile = await db_session.get(Profile, new_profile_id)
        assert new_profile.user_id == user.id
        assert new_profile.week_start_monday is False
        assert new_profile.pomodoro_work_minutes == 50

        # Tasks: subtask points at the imported parent, both in the new profile,
        # and the project link is remapped into the new profile's project.
        tasks = (
            (await db_session.execute(
                select(Task).where(Task.profile_id == new_profile_id)
            ))
            .scalars()
            .all()
        )
        assert len(tasks) == 2
        by_title = {t.title: t for t in tasks}
        parent = by_title["Parent task"]
        subtask = by_title["Subtask"]
        assert subtask.parent_id == parent.id
        assert parent.project_id is not None
        assert parent.project_id == subtask.project_id
        # The remapped project belongs to the new profile.
        from habit_tracker.schemas.db_models import Project

        new_project = await db_session.get(Project, parent.project_id)
        assert new_project.profile_id == new_profile_id

        # Countdown relinked to the imported parent task.
        countdown = (
            (await db_session.execute(
                select(Countdown).where(Countdown.profile_id == new_profile_id)
            ))
            .scalars()
            .one()
        )
        assert countdown.task_id == parent.id

        # Time entries: one attached to the imported task, one to the project.
        entries = (
            (await db_session.execute(
                select(TimeEntry).where(TimeEntry.profile_id == new_profile_id)
            ))
            .scalars()
            .all()
        )
        assert len(entries) == 2
        assert any(e.task_id == parent.id for e in entries)
        assert any(
            e.project_id == parent.project_id and e.task_id is None for e in entries
        )

        # Tracker hangs off the imported habit.
        new_habit = (
            (await db_session.execute(
                select(Habit).where(Habit.profile_id == new_profile_id)
            ))
            .scalars()
            .one()
        )
        tracker = (
            (await db_session.execute(
                select(Tracker).where(Tracker.habit_id == new_habit.id)
            ))
            .scalars()
            .one()
        )
        assert tracker.status == TrackerStatus.COMPLETED.value

        # Integration recreated disabled + tokenless for re-auth.
        conn = (
            (await db_session.execute(
                select(IntegrationConnection).where(
                    IntegrationConnection.profile_id == new_profile_id
                )
            ))
            .scalars()
            .one()
        )
        assert conn.enabled is False
        assert conn.has_token is False

    async def test_import_as_different_user_keeps_name_and_owner(
        self, client, db_session, login_as
    ):
        owner = UserFactory()
        other = UserFactory()
        await db_session.commit()
        src_profile, *_ = await _seed_full_profile(db_session, owner)

        await login_as(owner)
        export = (await client.get(f"/backup/profiles/{src_profile.id}")).json()

        await login_as(other)
        resp = await client.post("/backup/profiles", json=export)
        assert resp.status_code == 201
        summary = resp.json()
        # No name collision for a different user -> original name kept.
        assert summary["profile_name"] == "Work"
        new_profile = await db_session.get(Profile, summary["profile_id"])
        assert new_profile.user_id == other.id

    async def test_import_rejects_unknown_format(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        backup = ProfileBackup(
            exported_at=datetime(2026, 7, 24, 12, 0),
            profile={
                "name": "X",
                "color_start": "#e0763f",
                "color_end": "#c14e6a",
                "habits_enabled": True,
                "countdowns_enabled": True,
                "insights_enabled": True,
                "calendar_enabled": True,
                "publish_to_azure": False,
                "default_landing": "today",
                "week_start_monday": True,
                "use_habit_color_accent": False,
                "show_estimated_effort": False,
                "pomodoro_work_minutes": 25,
                "pomodoro_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_cycles": 4,
            },
        )
        payload = backup.model_dump(mode="json")
        payload["format"] = "some-other-tool"
        resp = await client.post("/backup/profiles", json=payload)
        assert resp.status_code == 400
        assert "format" in resp.json()["detail"].lower()

    async def test_import_requires_authentication(
        self, client, db_session
    ):
        resp = await client.post("/backup/profiles", json={})
        assert resp.status_code in (401, 422)
