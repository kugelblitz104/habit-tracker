"""Tests for profile management endpoints."""

from datetime import datetime, timedelta
from typing import ClassVar

from sqlalchemy import select

from habit_tracker.schemas.db_models import Habit, Profile, Project, Task, User
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    UserFactory,
)


class TestListProfiles:
    """Tests for GET /profiles/ endpoint."""

    async def test_list_own_profiles_only(self, client, db_session, login_as):
        """User sees only their own profiles."""
        user = UserFactory(default_profile=False)
        other_user = UserFactory(default_profile=False)
        await db_session.commit()

        ProfileFactory(user=user, name="Personal")
        ProfileFactory(user=user, name="Work")
        ProfileFactory(user=other_user, name="Other")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/profiles/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        names = {p["name"] for p in data["profiles"]}
        assert names == {"Personal", "Work"}

    async def test_list_profiles_ordered_by_created_date(
        self, client, db_session, login_as
    ):
        """Profiles are ordered by creation date ascending."""
        user = UserFactory(default_profile=False)
        await db_session.commit()

        # Insert out of chronological order to prove the ordering is applied
        ProfileFactory(user=user, name="Newest", created_date=datetime.now())
        ProfileFactory(
            user=user, name="Oldest", created_date=datetime.now() - timedelta(days=2)
        )
        ProfileFactory(
            user=user, name="Middle", created_date=datetime.now() - timedelta(days=1)
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get("/profiles/")
        assert response.status_code == 200
        names = [p["name"] for p in response.json()["profiles"]]
        assert names == ["Oldest", "Middle", "Newest"]

    async def test_list_profiles_admin_with_user_id(self, client, db_session, login_as):
        """Admin can list another user's profiles via user_id."""
        admin = AdminUserFactory(default_profile=False)
        user = UserFactory(default_profile=False)
        await db_session.commit()

        ProfileFactory(user=admin, name="Admin Personal")
        ProfileFactory(user=user, name="Target Personal")
        await db_session.commit()

        await login_as(admin)

        response = await client.get("/profiles/", params={"user_id": user.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["profiles"][0]["name"] == "Target Personal"

    async def test_list_profiles_non_admin_with_other_user_id(
        self, client, db_session, login_as
    ):
        """Non-admin cannot list another user's profiles (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=other_user, name="Other Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/profiles/", params={"user_id": other_user.id})
        assert response.status_code == 403

    async def test_list_profiles_unauthenticated(self, client, db_session):
        """Unauthenticated request is rejected (401)."""
        response = await client.get("/profiles/")
        assert response.status_code == 401


class TestCreateProfile:
    """Tests for POST /profiles/ endpoint."""

    async def test_create_profile_basic(self, client, db_session, login_as):
        """Create profile with just a name and get defaults back."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post("/profiles/", json={"name": "Work"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Work"
        assert data["color_start"] == "#e0763f"
        assert data["color_end"] == "#c14e6a"
        assert data["habits_enabled"] is True
        assert data["calendar_enabled"] is True
        assert data["publish_to_azure"] is False
        assert data["default_landing"] == "today"
        assert data["week_start_monday"] is True
        assert data["use_habit_color_accent"] is False

    async def test_create_profile_all_fields(self, client, db_session, login_as):
        """Create profile with all fields and get them echoed back."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/profiles/",
            json={
                "name": "Work",
                "color_start": "#112233",
                "color_end": "#445566",
                "habits_enabled": False,
                "calendar_enabled": False,
                "publish_to_azure": True,
                "default_landing": "habits",
                "week_start_monday": False,
                "use_habit_color_accent": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Work"
        assert data["color_start"] == "#112233"
        assert data["color_end"] == "#445566"
        assert data["habits_enabled"] is False
        assert data["calendar_enabled"] is False
        assert data["publish_to_azure"] is True
        assert data["default_landing"] == "habits"
        assert data["week_start_monday"] is False
        assert data["use_habit_color_accent"] is True

    async def test_create_profile_duplicate_name(self, client, db_session, login_as):
        """Duplicate profile name for the same user is rejected (409)."""
        user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(user)

        response = await client.post("/profiles/", json={"name": "Work"})
        assert response.status_code == 409

    async def test_create_profile_same_name_different_user(
        self, client, db_session, login_as
    ):
        """Two different users may each have a profile with the same name."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=other_user, name="Work")
        await db_session.commit()

        await login_as(user)

        response = await client.post("/profiles/", json={"name": "Work"})
        assert response.status_code == 201

    async def test_create_profile_invalid_color(self, client, db_session, login_as):
        """Invalid gradient color is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/profiles/", json={"name": "Work", "color_start": "red"}
        )
        assert response.status_code == 422

    async def test_create_profile_invalid_default_landing(
        self, client, db_session, login_as
    ):
        """Invalid default_landing is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/profiles/", json={"name": "Work", "default_landing": "dashboard"}
        )
        assert response.status_code == 422

    async def test_create_profile_user_id_not_spoofable(
        self, client, db_session, login_as
    ):
        """A user_id in the payload is ignored - profile belongs to caller."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/profiles/", json={"name": "Sneaky", "user_id": other_user.id}
        )
        assert response.status_code == 201
        profile_id = response.json()["id"]

        db_profile = await db_session.get(Profile, profile_id)
        assert db_profile.user_id == user.id


class TestGetProfile:
    """Tests for GET /profiles/{profile_id} endpoint."""

    async def test_get_own_profile(self, client, db_session, login_as):
        """User can retrieve their own profile."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/profiles/{profile.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == profile.id
        assert data["name"] == "Personal"

    async def test_get_other_user_profile(self, client, db_session, login_as):
        """User cannot access another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=other_user, name="Other")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/profiles/{profile.id}")
        assert response.status_code == 403

    async def test_get_profile_as_admin(self, client, db_session, login_as):
        """Admin can access any profile."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/profiles/{profile.id}")
        assert response.status_code == 200

    async def test_get_nonexistent_profile(self, client, db_session, login_as):
        """Return 404 for non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/profiles/99999")
        assert response.status_code == 404


class TestPatchProfile:
    """Tests for PATCH /profiles/{profile_id} endpoint."""

    async def test_patch_profile_partial_update(self, client, db_session, login_as):
        """Updating one field leaves the others untouched."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(
            user=user, name="Personal", color_start="#112233", default_landing="habits"
        )
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"name": "Renamed"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Renamed"
        assert data["color_start"] == "#112233"
        assert data["default_landing"] == "habits"

    async def test_patch_profile_sets_updated_date(self, client, db_session, login_as):
        """Patching a profile stamps its updated_date."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"name": "Renamed"}
        )
        assert response.status_code == 200
        assert response.json()["updated_date"] is not None

    async def test_patch_profile_duplicate_name(self, client, db_session, login_as):
        """Renaming to another of the user's profile names is rejected (409)."""
        user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=user, name="Personal")
        profile = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"name": "Personal"}
        )
        assert response.status_code == 409

    async def test_patch_profile_toggles(self, client, db_session, login_as):
        """Feature toggles can be flipped."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}",
            json={
                "habits_enabled": False,
                "calendar_enabled": False,
                "publish_to_azure": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["habits_enabled"] is False
        assert data["calendar_enabled"] is False
        assert data["publish_to_azure"] is True

    async def test_patch_profile_week_start_monday(self, client, db_session, login_as):
        """week_start_monday can be flipped off and persists on read."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"week_start_monday": False}
        )
        assert response.status_code == 200
        assert response.json()["week_start_monday"] is False

        # Persists on a subsequent read
        response = await client.get(f"/profiles/{profile.id}")
        assert response.status_code == 200
        assert response.json()["week_start_monday"] is False

    async def test_patch_profile_use_habit_color_accent(
        self, client, db_session, login_as
    ):
        """use_habit_color_accent can be opted into and persists on read."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"use_habit_color_accent": True}
        )
        assert response.status_code == 200
        assert response.json()["use_habit_color_accent"] is True

        # Persists on a subsequent read
        response = await client.get(f"/profiles/{profile.id}")
        assert response.status_code == 200
        assert response.json()["use_habit_color_accent"] is True

    async def test_patch_profile_null_preference_flag(
        self, client, db_session, login_as
    ):
        """An explicit null for a non-nullable preference flag is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"week_start_monday": None}
        )
        assert response.status_code == 422

        response = await client.patch(
            f"/profiles/{profile.id}", json={"use_habit_color_accent": None}
        )
        assert response.status_code == 422

    async def test_patch_profile_invalid_default_landing(
        self, client, db_session, login_as
    ):
        """Invalid default_landing on patch is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/profiles/{profile.id}", json={"default_landing": "nope"}
        )
        assert response.status_code == 422

    async def test_patch_profile_null_name(self, client, db_session, login_as):
        """An explicit null for the non-nullable name is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/profiles/{profile.id}", json={"name": None})
        assert response.status_code == 422

    async def test_patch_other_user_profile(self, client, db_session, login_as):
        """User cannot patch another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=other_user, name="Other")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(f"/profiles/{profile.id}", json={"name": "Hax"})
        assert response.status_code == 403


class TestDeleteProfile:
    """Tests for DELETE /profiles/{profile_id} endpoint."""

    async def test_delete_profile_cascades(self, client, db_session, login_as):
        """Deleting a profile cascades to its habits, projects, and tasks."""
        user = UserFactory()
        await db_session.commit()

        keep = ProfileFactory(user=user, name="Keep")
        doomed = ProfileFactory(user=user, name="Doomed")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=doomed)
        project = ProjectFactory(profile=doomed)
        await db_session.commit()

        task_in_project = TaskFactory(profile=doomed, project=project)
        loose_task = TaskFactory(profile=doomed)
        surviving_task = TaskFactory(profile=keep)
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/profiles/{doomed.id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Profile).filter(Profile.id == doomed.id)
        )
        assert result.scalar_one_or_none() is None
        result = await db_session.execute(select(Habit).filter(Habit.id == habit.id))
        assert result.scalar_one_or_none() is None
        result = await db_session.execute(
            select(Project).filter(Project.id == project.id)
        )
        assert result.scalar_one_or_none() is None
        result = await db_session.execute(
            select(Task).filter(Task.id.in_([task_in_project.id, loose_task.id]))
        )
        assert result.scalars().all() == []

        # The other profile and its task are untouched
        result = await db_session.execute(select(Profile).filter(Profile.id == keep.id))
        assert result.scalar_one_or_none() is not None
        result = await db_session.execute(
            select(Task).filter(Task.id == surviving_task.id)
        )
        assert result.scalar_one_or_none() is not None

    async def test_delete_last_profile(self, client, db_session, login_as):
        """The user's last remaining profile cannot be deleted (400)."""
        user = UserFactory(default_profile=False)
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/profiles/{profile.id}")
        assert response.status_code == 400

        result = await db_session.execute(
            select(Profile).filter(Profile.id == profile.id)
        )
        assert result.scalar_one_or_none() is not None

    async def test_delete_other_user_profile(self, client, db_session, login_as):
        """User cannot delete another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=other_user, name="Other A")
        profile = ProfileFactory(user=other_user, name="Other B")
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/profiles/{profile.id}")
        assert response.status_code == 403


class TestRegisterCreatesDefaultProfile:
    """Tests for the default profile created by POST /auth/register."""

    async def test_register_creates_personal_profile(self, client, db_session):
        """Registering creates exactly one 'Personal' profile for the user."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "freshuser",
                "first_name": "Fresh",
                "last_name": "User",
                "email": "freshuser@example.com",
                "plaintext_password": "password123",
            },
        )
        assert response.status_code == 201

        result = await db_session.execute(
            select(User).filter(User.username == "freshuser")
        )
        new_user = result.scalar_one()

        result = await db_session.execute(
            select(Profile).filter(Profile.user_id == new_user.id)
        )
        profiles = result.scalars().all()
        assert len(profiles) == 1
        assert profiles[0].name == "Personal"


class TestHabitProfileIntegration:
    """Tests for habit endpoints' profile resolution and filtering."""

    HABIT_PAYLOAD: ClassVar[dict[str, str | int]] = {
        "name": "Drink Water",
        "question": "Did you drink 8 glasses?",
        "color": "#00FF00",
        "frequency": 1,
        "range": 1,
    }

    async def test_create_habit_with_explicit_profile_id(
        self, client, db_session, login_as
    ):
        """An explicit valid profile_id is honored."""
        user = UserFactory()
        await db_session.commit()

        ProfileFactory(
            user=user, name="Oldest", created_date=datetime.now() - timedelta(days=2)
        )
        newer = ProfileFactory(user=user, name="Newer", created_date=datetime.now())
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/", json={**self.HABIT_PAYLOAD, "profile_id": newer.id}
        )
        assert response.status_code == 201
        assert response.json()["profile_id"] == newer.id

    async def test_create_habit_with_foreign_profile_id(
        self, client, db_session, login_as
    ):
        """A profile belonging to another user is rejected (400)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=user, name="Mine")
        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/", json={**self.HABIT_PAYLOAD, "profile_id": foreign.id}
        )
        assert response.status_code == 400

    async def test_list_habits_profile_filter(self, client, db_session, login_as):
        """GET /habits/?profile_id only returns that profile's habits."""
        user = UserFactory()
        await db_session.commit()

        profile1 = ProfileFactory(user=user, name="One")
        profile2 = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit1 = HabitFactory(user=user, profile=profile1)
        habit2 = HabitFactory(user=user, profile=profile1)
        HabitFactory(user=user, profile=profile2)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/", params={"profile_id": profile1.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {h["id"] for h in data["habits"]}
        assert ids == {habit1.id, habit2.id}

    async def test_admin_patch_habit_with_owner_profile(
        self, client, db_session, login_as
    ):
        """Admin can move a user's habit between that user's own profiles."""
        admin = AdminUserFactory()
        user = UserFactory(default_profile=False)
        await db_session.commit()

        profile1 = ProfileFactory(user=user, name="One")
        profile2 = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        habit = HabitFactory(user=user, profile=profile1)
        await db_session.commit()

        await login_as(admin)

        response = await client.patch(
            f"/habits/{habit.id}", json={"profile_id": profile2.id}
        )
        assert response.status_code == 200
        assert response.json()["profile_id"] == profile2.id

    async def test_admin_cannot_attach_own_profile_to_others_habit(
        self, client, db_session, login_as
    ):
        """A profile that does not belong to the habit owner is rejected."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        admin_profile = admin.profiles[0]
        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(admin)

        response = await client.patch(
            f"/habits/{habit.id}", json={"profile_id": admin_profile.id}
        )
        assert response.status_code == 400

    async def test_list_habits_wrong_owner_profile(self, client, db_session, login_as):
        """A profile_id belonging to another user is refused (403), not 404."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        ProfileFactory(user=user, name="Mine")
        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/", params={"profile_id": foreign.id})
        assert response.status_code == 403
