"""Tests for the Markdown task export endpoint and formatter."""

from datetime import date, datetime, time, timedelta

from habit_tracker.constants import TaskStatus
from habit_tracker.schemas.db_models import Task
from habit_tracker.services.task_export import render_tasks_markdown
from tests.factories import (
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


def _task(**overrides) -> Task:
    """Build a transient Task for pure formatter tests.

    Column defaults only apply on INSERT, so every field the formatter reads
    is set explicitly here.
    """
    fields = {
        "title": "A task",
        "notes": None,
        "priority": 0,
        "due_date": None,
        "due_time": None,
        "scheduled_date": None,
        "scheduled_time": None,
        "status": TaskStatus.OPEN.value,
        "block_reason": None,
        "project_id": None,
        "parent_id": None,
        "closed_date": None,
        "created_date": datetime(2026, 1, 1, 12, 0),
    }
    fields.update(overrides)
    return Task(**fields)


class TestRenderTasksMarkdown:
    """Unit tests for the pure formatter (no HTTP, no database)."""

    def test_active_ordering_priority_then_due_then_created(self):
        """Within a band: priority desc, due asc (nulls last), created asc."""
        today = date(2026, 7, 9)
        soon_due_near = _task(title="Due near", due_date=today + timedelta(days=3))
        soon_due_far = _task(title="Due far", due_date=today + timedelta(days=5))
        soon_priority = _task(title="Priority two", priority=2)
        doc = render_tasks_markdown(
            "Personal",
            [soon_due_far, soon_due_near, soon_priority],
            {},
            today=today,
        )
        assert (
            doc.index("Priority two") < doc.index("Due near") < doc.index("Due far")
        )

    def test_subtasks_nest_under_parent_not_top_level(self):
        """Subtasks render indented under their parent, never top-level."""
        today = date(2026, 7, 9)
        parent = _task(title="Plan the offsite")  # priority 0 -> whenever
        parent.id = 1
        # Priority 3 would band the subtask "now" on its own - it must still
        # render under its parent in the Whenever section, indented
        sub_open = _task(title="Book the venue", parent_id=1, priority=3)
        sub_done = _task(
            title="Pick a date",
            parent_id=1,
            status=TaskStatus.DONE.value,
            closed_date=datetime(2026, 7, 8),
        )
        doc = render_tasks_markdown(
            "Personal", [sub_done, parent, sub_open], {}, today=today
        )
        assert "- [ ] Plan the offsite\n  - [ ] Book the venue" in doc
        assert "  - [x] Pick a date" in doc
        # Never as a top-level checklist line, and the subtask's own
        # priority/status never open a band section of their own
        assert "\n- [ ] Book the venue" not in doc
        assert "\n- [x] Pick a date" not in doc
        assert "## Now" not in doc
        assert "## Completed & cancelled" not in doc

    def test_subtask_detail_bullets_indent_below_subtask(self):
        """A subtask's detail bullets indent one level below its own line."""
        today = date(2026, 7, 9)
        parent = _task(title="Parent task")
        parent.id = 7
        _sub = _task(
            title="Blocked subtask",
            parent_id=7,
            status=TaskStatus.BLOCKED.value,
            priority=2,
            block_reason="waiting on vendor",
            notes="First line\nSecond line",
        )
        doc = render_tasks_markdown("Personal", [parent, _sub], {}, today=today)
        assert (
            "- [ ] Parent task\n"
            "  - [ ] Blocked subtask\n"
            "    - Status: Blocked\n"
            "    - Priority: Medium\n"
            "    - Blocked: waiting on vendor\n"
            "    - Notes:\n"
            "      First line\n"
            "      Second line" in doc
        )

    def test_subtask_of_hidden_parent_renders_in_closed_section(self):
        """Subtasks follow their parent into whatever section it lands in."""
        today = date(2026, 7, 9)
        parent = _task(
            title="Cancelled parent",
            status=TaskStatus.CANCELLED.value,
            closed_date=datetime(2026, 7, 1),
        )
        parent.id = 3
        _sub = _task(title="Leftover subtask", parent_id=3)
        doc = render_tasks_markdown("Personal", [parent, _sub], {}, today=today)
        completed_at = doc.index("## Completed & cancelled")
        assert doc.index("  - [ ] Leftover subtask") > completed_at
        assert "## Whenever" not in doc  # the subtask did not band on its own

    def test_hidden_ordering_most_recently_closed_first(self):
        """The closed section is ordered by closed date, most recent first."""
        today = date(2026, 7, 9)
        old = _task(
            title="Closed long ago",
            status=TaskStatus.DONE.value,
            closed_date=datetime(2026, 6, 1),
        )
        recent = _task(
            title="Closed yesterday",
            status=TaskStatus.DONE.value,
            closed_date=datetime(2026, 7, 8),
        )
        doc = render_tasks_markdown("Personal", [old, recent], {}, today=today)
        assert doc.index("Closed yesterday") < doc.index("Closed long ago")


class TestExportTasksMarkdown:
    """Tests for GET /tasks/export endpoint."""

    async def test_export_groups_tasks_by_band(
        self, client, db_session, setup_factories
    ):
        """Tasks land in Now/Soon/Whenever/Completed sections by band."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(profile=profile, title="Urgent thing", priority=3)
        TaskFactory(
            profile=profile,
            title="Upcoming thing",
            due_date=date.today() + timedelta(days=3),
        )
        TaskFactory(profile=profile, title="Someday thing")
        DoneTaskFactory(profile=profile, title="Finished thing")
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text

        # Sections appear in order, each task inside its own section
        assert (
            body.index("## Now")
            < body.index("- [ ] Urgent thing")
            < body.index("## Soon")
            < body.index("- [ ] Upcoming thing")
            < body.index("## Whenever")
            < body.index("- [ ] Someday thing")
            < body.index("## Completed & cancelled")
            < body.index("- [x] Finished thing")
        )

    async def test_export_subtasks_nested_under_parent(
        self, client, db_session, setup_factories
    ):
        """Subtasks export as indented checklist lines under their parent."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        parent = TaskFactory(profile=profile, title="Plan the offsite")
        await db_session.commit()
        base = datetime(2026, 7, 1, 9, 0)
        TaskFactory(
            profile=profile,
            title="Book the venue",
            parent_id=parent.id,
            created_date=base,
        )
        DoneTaskFactory(
            profile=profile,
            title="Pick a date",
            parent_id=parent.id,
            created_date=base + timedelta(seconds=1),
        )
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text
        assert (
            "- [ ] Plan the offsite\n"
            "  - [ ] Book the venue\n"
            "  - [x] Pick a date" in body
        )
        # The done subtask never surfaces in the Completed section
        assert "## Completed & cancelled" not in body

    async def test_export_header_has_profile_name_and_date(
        self, client, db_session, setup_factories
    ):
        """The document header carries the profile name and export date."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert "# Work — Tasks" in response.text
        assert f"_Exported {date.today().isoformat()}_" in response.text

    async def test_export_done_checked_cancelled_unchecked(
        self, client, db_session, setup_factories
    ):
        """Done tasks get [x]; cancelled stay [ ] with a Status line."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        DoneTaskFactory(profile=profile, title="Finished thing")
        TaskFactory(
            profile=profile,
            title="Abandoned thing",
            status=TaskStatus.CANCELLED,
            closed_date=datetime.now(),
        )
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text
        assert "- [x] Finished thing" in body
        assert "- [ ] Abandoned thing\n  - Status: Cancelled" in body

    async def test_export_optional_fields_omitted_when_unset(
        self, client, db_session, setup_factories
    ):
        """A bare open task renders as a single checklist line, no details."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(profile=profile, title="Bare task")
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text
        assert "- [ ] Bare task" in body
        for detail in ("Status:", "Priority:", "Due:", "Scheduled:", "Project:",
                       "Blocked:", "Notes:"):
            assert detail not in body

    async def test_export_renders_set_detail_fields(
        self, client, db_session, setup_factories
    ):
        """Status/priority/due/scheduled/project/block reason all render."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        project = ProjectFactory(profile=profile, name="Website revamp")
        await db_session.commit()

        due = date.today() + timedelta(days=10)
        TaskFactory(
            profile=profile,
            title="Blocked task",
            status=TaskStatus.BLOCKED,
            priority=3,
            due_date=due,
            due_time=time(14, 30),
            project=project,
            block_reason="waiting on vendor",
        )
        scheduled = date.today() + timedelta(days=2)
        TaskFactory(
            profile=profile,
            title="Scheduled task",
            status=TaskStatus.SCHEDULED,
            priority=1,
            scheduled_date=scheduled,
            scheduled_time=time(9, 15),
        )
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text
        assert "  - Status: Blocked" in body
        assert "  - Priority: High" in body
        assert f"  - Due: {due.isoformat()} 14:30" in body
        assert "  - Project: Website revamp" in body
        assert "  - Blocked: waiting on vendor" in body
        assert "  - Status: Scheduled" in body
        assert "  - Priority: Low" in body
        assert f"  - Scheduled: {scheduled.isoformat()} 09:15" in body

    async def test_export_multiline_notes_indented(
        self, client, db_session, setup_factories
    ):
        """Every notes line is indented under the task's Notes bullet."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        TaskFactory(
            profile=profile,
            title="Task with notes",
            notes="First line\nSecond line",
        )
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert (
            "- [ ] Task with notes\n  - Notes:\n    First line\n    Second line"
            in response.text
        )

    async def test_export_empty_profile_valid_doc(
        self, client, db_session, setup_factories
    ):
        """A profile without tasks exports header only, sections omitted."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Empty")
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        body = response.text
        assert "# Empty — Tasks" in body
        assert "## " not in body  # empty sections are omitted entirely

    async def test_export_unknown_profile_returns_404(
        self, client, db_session, setup_factories
    ):
        """Exporting a nonexistent profile returns 404."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": 999999})
        assert response.status_code == 404
        assert response.json()["detail"] == "Profile not found"

    async def test_export_other_users_profile_forbidden(
        self, client, db_session, setup_factories
    ):
        """Exporting another user's profile returns 403."""
        owner = UserFactory()
        intruder = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=owner, name="Private")
        await db_session.commit()

        await login_as(client, intruder)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 403

    async def test_export_content_type_is_markdown(
        self, client, db_session, setup_factories
    ):
        """The response is raw text/markdown, not JSON-wrapped."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)
        response = await client.get("/tasks/export", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
