"""Tests for project management endpoints."""

from datetime import datetime

from sqlalchemy import select

from habit_tracker.constants import TaskStatus
from habit_tracker.schemas.db_models import Project, Task
from tests.factories import (
    DoneTaskFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    UserFactory,
)


class TestListProjects:
    """Tests for GET /projects/ endpoint."""

    async def test_list_projects_requires_profile_id(
        self, client, db_session, login_as
    ):
        """profile_id query parameter is required (422 if missing)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/")
        assert response.status_code == 422

    async def test_list_projects_unknown_profile(self, client, db_session, login_as):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/", params={"profile_id": 99999})
        assert response.status_code == 404

    async def test_list_projects_foreign_profile(self, client, db_session, login_as):
        """Cannot list projects of another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/", params={"profile_id": foreign.id})
        assert response.status_code == 403

    async def test_list_projects_scoped_to_profile(self, client, db_session, login_as):
        """Only projects of the requested profile are returned."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project1 = ProjectFactory(profile=profile)
        project2 = ProjectFactory(profile=profile)
        ProjectFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {p["id"] for p in data["projects"]}
        assert ids == {project1.id, project2.id}

    async def test_list_projects_include_archived(self, client, db_session, login_as):
        """Archived projects are hidden by default and shown with the flag."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        active = ProjectFactory(profile=profile, archived=False)
        archived = ProjectFactory(profile=profile, archived=True)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["projects"][0]["id"] == active.id

        response = await client.get(
            "/projects/", params={"profile_id": profile.id, "include_archived": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {p["id"] for p in data["projects"]}
        assert ids == {active.id, archived.id}

    async def test_list_projects_task_counts(self, client, db_session, login_as):
        """open_count/done_count are correct; cancelled counts in neither."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        TaskFactory(profile=profile, project=project, status=TaskStatus.OPEN)
        TaskFactory(profile=profile, project=project, status=TaskStatus.IN_PROGRESS)
        TaskFactory(profile=profile, project=project, status=TaskStatus.BLOCKED)
        DoneTaskFactory(profile=profile, project=project)
        DoneTaskFactory(profile=profile, project=project)
        TaskFactory(
            profile=profile,
            project=project,
            status=TaskStatus.CANCELLED,
            closed_date=datetime.now(),
        )
        # Task outside the project must not be counted
        TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()["projects"][0]
        assert data["open_count"] == 3
        assert data["done_count"] == 2


class TestCreateProject:
    """Tests for POST /projects/ endpoint."""

    async def test_create_project_basic(self, client, db_session, login_as):
        """Create project and get its fields echoed back with zero counts."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/projects/",
            json={
                "profile_id": profile.id,
                "name": "Wedding",
                "color": "#AA00BB",
                "notes": "Planning notes",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["profile_id"] == profile.id
        assert data["name"] == "Wedding"
        assert data["color"] == "#AA00BB"
        assert data["notes"] == "Planning notes"
        assert data["archived"] is False
        assert data["open_count"] == 0
        assert data["done_count"] == 0

    async def test_create_project_foreign_profile(self, client, db_session, login_as):
        """Cannot create a project in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/projects/",
            json={"profile_id": foreign.id, "name": "Nope", "color": "#123456"},
        )
        assert response.status_code == 403

    async def test_create_project_unknown_profile(self, client, db_session, login_as):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/projects/",
            json={"profile_id": 99999, "name": "Nope", "color": "#123456"},
        )
        assert response.status_code == 404

    async def test_create_project_invalid_color(self, client, db_session, login_as):
        """Invalid color is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/projects/",
            json={"profile_id": profile.id, "name": "Bad", "color": "blue"},
        )
        assert response.status_code == 422


class TestGetProject:
    """Tests for GET /projects/{project_id} endpoint."""

    async def test_get_project_with_counts(self, client, db_session, login_as):
        """Retrieve a project including its task counts."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        TaskFactory(profile=profile, project=project, status=TaskStatus.OPEN)
        DoneTaskFactory(profile=profile, project=project)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/projects/{project.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == project.id
        assert data["open_count"] == 1
        assert data["done_count"] == 1

    async def test_get_nonexistent_project(self, client, db_session, login_as):
        """Return 404 for non-existent project."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/projects/99999")
        assert response.status_code == 404

    async def test_get_other_user_project(self, client, db_session, login_as):
        """User cannot access a project in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        project = ProjectFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/projects/{project.id}")
        assert response.status_code == 403


class TestProjectSlugs:
    """Tests for server-assigned slugs and GET /projects/by-slug/{slug}.

    The slugify/numbering rules themselves are pinned DB-free in test_slugs.py
    and exercised through tasks in test_tasks.py::TestTaskSlugs; this class
    covers the projects router's own wiring.
    """

    async def test_create_assigns_slug_from_name(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        response = await client.post(
            "/projects/",
            json={
                "profile_id": profile.id,
                "name": "Alpha Project",
                "color": "#336699",
            },
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "alpha-project"

    async def test_duplicate_names_number_off_each_other(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        slugs = []
        for _ in range(2):
            response = await client.post(
                "/projects/",
                json={"profile_id": profile.id, "name": "Alpha", "color": "#336699"},
            )
            assert response.status_code == 201
            slugs.append(response.json()["slug"])

        assert slugs == ["alpha", "alpha-2"]

    async def test_get_by_slug_matches_the_by_id_response(
        self, client, db_session, login_as
    ):
        """Including the task counts, which the by-slug route computes too."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={
                "profile_id": profile.id,
                "name": "Alpha Project",
                "color": "#336699",
            },
        )
        project_id = created.json()["id"]

        TaskFactory(profile=profile, project_id=project_id)
        DoneTaskFactory(profile=profile, project_id=project_id)
        await db_session.commit()

        by_slug = await client.get(
            "/projects/by-slug/alpha-project", params={"profile_id": profile.id}
        )
        assert by_slug.status_code == 200
        assert by_slug.json()["open_count"] == 1
        assert by_slug.json()["done_count"] == 1

        by_id = await client.get(f"/projects/{project_id}")
        assert by_id.json() == by_slug.json()

    async def test_get_by_slug_unknown_slug_404(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/projects/by-slug/nothing-here", params={"profile_id": profile.id}
        )
        assert response.status_code == 404

    async def test_get_by_slug_does_not_cross_profiles(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        personal = ProfileFactory(user=user, name="Personal")
        work = ProfileFactory(user=user, name="Work")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={"profile_id": personal.id, "name": "Alpha", "color": "#336699"},
        )
        assert created.status_code == 201

        response = await client.get(
            "/projects/by-slug/alpha", params={"profile_id": work.id}
        )
        assert response.status_code == 404

    async def test_get_by_slug_other_users_profile_403(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()
        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/projects/by-slug/anything", params={"profile_id": foreign_profile.id}
        )
        assert response.status_code == 403

    async def test_rename_reslugs_and_old_slug_stops_resolving(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={"profile_id": profile.id, "name": "Alpha", "color": "#336699"},
        )
        project_id = created.json()["id"]

        patched = await client.patch(f"/projects/{project_id}", json={"name": "Beta"})
        assert patched.status_code == 200
        assert patched.json()["slug"] == "beta"

        stale = await client.get(
            "/projects/by-slug/alpha", params={"profile_id": profile.id}
        )
        assert stale.status_code == 404
        assert (await client.get(f"/projects/{project_id}")).status_code == 200

    async def test_rename_to_same_slug_does_not_bump_itself(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={"profile_id": profile.id, "name": "Alpha", "color": "#336699"},
        )
        patched = await client.patch(
            f"/projects/{created.json()['id']}", json={"name": "  Alpha!  "}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "alpha"

    async def test_patch_without_name_keeps_the_slug(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={"profile_id": profile.id, "name": "Alpha", "color": "#336699"},
        )
        patched = await client.patch(
            f"/projects/{created.json()['id']}", json={"color": "#112233"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "alpha"

    async def test_slug_is_read_only(self, client, db_session, login_as):
        """`slug` is absent from ProjectCreate/ProjectUpdate, so a client cannot
        set it - the derived slug wins."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/projects/",
            json={
                "profile_id": profile.id,
                "name": "Alpha",
                "color": "#336699",
                "slug": "hand-picked",
            },
        )
        assert created.status_code == 201
        assert created.json()["slug"] == "alpha"

        patched = await client.patch(
            f"/projects/{created.json()['id']}", json={"slug": "hand-picked"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "alpha"


class TestPatchProject:
    """Tests for PATCH /projects/{project_id} endpoint."""

    async def test_patch_project_rename(self, client, db_session, login_as):
        """Rename a project."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile, name="Old Name")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/projects/{project.id}", json={"name": "New Name"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_patch_project_archive(self, client, db_session, login_as):
        """Archive a project."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile, archived=False)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/projects/{project.id}", json={"archived": True}
        )
        assert response.status_code == 200
        assert response.json()["archived"] is True

    async def test_patch_project_notes(self, client, db_session, login_as):
        """Update project notes."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/projects/{project.id}", json={"notes": "## Updated markdown"}
        )
        assert response.status_code == 200
        assert response.json()["notes"] == "## Updated markdown"

    async def test_patch_project_move_to_own_profile(
        self, client, db_session, login_as
    ):
        """Move a project to another profile of the same user."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/projects/{project.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 200
        assert response.json()["profile_id"] == other_profile.id

    async def test_patch_project_move_carries_tasks(self, client, db_session, login_as):
        """Moving a project to another profile moves its tasks with it."""
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
            f"/projects/{project.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 200

        await db_session.refresh(task)
        assert task.profile_id == other_profile.id

    async def test_patch_project_null_name(self, client, db_session, login_as):
        """An explicit null for the non-nullable name is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/projects/{project.id}", json={"name": None})
        assert response.status_code == 422

    async def test_patch_project_move_to_other_user_profile(
        self, client, db_session, login_as
    ):
        """Moving a project to another user's profile is rejected (400)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Mine")
        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/projects/{project.id}", json={"profile_id": foreign.id}
        )
        assert response.status_code == 400


class TestDeleteProject:
    """Tests for DELETE /projects/{project_id} endpoint."""

    async def test_delete_project_keeps_tasks(self, client, db_session, login_as):
        """Deleting a project keeps its tasks with project_id cleared."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        project = ProjectFactory(profile=profile)
        await db_session.commit()

        task = TaskFactory(profile=profile, project=project)
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/projects/{project.id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Project).filter(Project.id == project.id)
        )
        assert result.scalar_one_or_none() is None

        # The task survives with its project association cleared by the DB
        await db_session.refresh(task)
        assert task.project_id is None

    async def test_delete_other_user_project(self, client, db_session, login_as):
        """User cannot delete a project in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        project = ProjectFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/projects/{project.id}")
        assert response.status_code == 403

    async def test_delete_nonexistent_project(self, client, db_session, login_as):
        """Return 404 for non-existent project."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/projects/99999")
        assert response.status_code == 404


class TestDeleteAllProjects:
    """Tests for DELETE /projects/ (bulk delete, profile-scoped)."""

    async def test_deletes_only_this_profile(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        ProjectFactory(profile=profile)
        ProjectFactory(profile=profile)
        keep = ProjectFactory(profile=other)
        await db_session.commit()

        await login_as(user)
        response = await client.delete("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Project))).scalars().all()
        assert [p.id for p in remaining] == [keep.id]

    async def test_tasks_kept_and_unassigned(self, client, db_session, login_as):
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

        await login_as(user)
        response = await client.delete("/projects/", params={"profile_id": profile.id})
        assert response.status_code == 200

        db_session.expire_all()
        surviving = await db_session.get(Task, task_id)
        assert surviving is not None
        assert surviving.project_id is None
