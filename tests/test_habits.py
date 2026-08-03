"""Tests for habit management endpoints."""

from datetime import date, datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

from sqlalchemy import select

from habit_tracker.constants import TrackerStatus
from habit_tracker.schemas.db_models import Habit, Tracker
from tests.factories import (
    AdminUserFactory,
    HabitFactory,
    ProfileFactory,
    TrackerFactory,
    UserFactory,
)


class TestCreateHabit:
    """Tests for POST /habits/ endpoint."""

    async def test_create_habit_basic(self, client, db_session, login_as):
        """Create habit with minimal required fields."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Drink Water",
                "question": "Did you drink 8 glasses?",
                "color": "#00FF00",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Drink Water"
        assert data["question"] == "Did you drink 8 glasses?"
        assert data["color"] == "#00FF00"

    async def test_create_habit_all_fields(self, client, db_session, login_as):
        """Create habit with all optional fields."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Exercise",
                "question": "Did you exercise today?",
                "color": "#FF0000",
                "frequency": 5,
                "range": 7,
                "reminder": True,
                "notes": "Morning workout routine",
                "archived": False,
                "sort_order": 10,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Exercise"
        assert data["frequency"] == 5
        assert data["range"] == 7
        assert data["reminder"] is True
        assert data["notes"] == "Morning workout routine"
        assert data["sort_order"] == 10

    async def test_create_habit_auto_assigns_user(self, client, db_session, login_as):
        """Verify habit is assigned to current user."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201
        habit_id = response.json()["id"]

        habit = await db_session.get(Habit, habit_id)
        assert habit.profile_id == user.profiles[0].id

    async def test_create_habit_invalid_color(self, client, db_session, login_as):
        """Reject invalid color format (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "blue",  # Invalid - not hex
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_negative_frequency(self, client, db_session, login_as):
        """Reject negative frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": -1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_negative_range(self, client, db_session, login_as):
        """Reject negative range (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": -1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_zero_frequency(self, client, db_session, login_as):
        """Reject zero frequency (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 0,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_zero_range(self, client, db_session, login_as):
        """Reject zero range (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 0,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_missing_required_fields(
        self, client, db_session, login_as
    ):
        """Reject missing required fields (422)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        # Missing name
        response = await client.post(
            "/habits/",
            json={
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 422

    async def test_create_habit_with_sort_order(self, client, db_session, login_as):
        """Create habit with custom sort order."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Sorted Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "sort_order": 99,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201
        assert response.json()["sort_order"] == 99

    async def test_create_habit_archived_flag(self, client, db_session, login_as):
        """Create habit with archived flag."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "name": "Archived Habit",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "archived": True,
                "profile_id": user.profiles[0].id,
            },
        )
        assert response.status_code == 201
        assert response.json()["archived"] is True


class TestGetHabit:
    """Tests for GET /habits/{habit_id} endpoint."""

    async def test_get_own_habit(self, client, db_session, login_as):
        """User can retrieve their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="My Habit", color="#123456")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == habit.id
        assert data["name"] == "My Habit"

    async def test_get_other_user_habit(self, client, db_session, login_as):
        """User cannot access other user's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_get_habit_as_admin(self, client, db_session, login_as):
        """Admin can access any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(admin)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200

    async def test_get_nonexistent_habit(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/99999")
        assert response.status_code == 404

    async def test_get_habit_includes_today_status(self, client, db_session, login_as):
        """Verify completed_today and skipped_today fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.COMPLETED)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is True
        assert data["skipped_today"] is False

    async def test_get_habit_today_status_with_tracker(
        self, client, db_session, login_as
    ):
        """Verify status when tracker exists for today."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.SKIPPED)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is True

    async def test_get_habit_today_status_without_tracker(
        self, client, db_session, login_as
    ):
        """Verify default false when no tracker."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completed_today"] is False
        assert data["skipped_today"] is False

    async def test_get_habit_today_status_honors_tz(self, client, db_session, login_as):
        """completed_today is computed against "today" in the requested zone.

        Etc/GMT+12 (UTC-12) and Etc/GMT-14 (UTC+14) are 26 hours apart, so
        their calendar dates always differ. A tracker dated "today" in one
        zone is therefore completed_today only for that zone, regardless of
        when the test runs.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tz_name, other_tz_name = "Etc/GMT-14", "Etc/GMT+12"
        expected_today = datetime.now(ZoneInfo(tz_name)).date()
        TrackerFactory(
            habit=habit, dated=expected_today, status=TrackerStatus.COMPLETED
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}", params={"tz": tz_name})
        assert response.status_code == 200
        assert response.json()["completed_today"] is True

        response = await client.get(f"/habits/{habit.id}", params={"tz": other_tz_name})
        assert response.status_code == 200
        assert response.json()["completed_today"] is False

    async def test_get_habit_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/habits/{habit.id}", params={"tz": "Not/AZone"})
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]


class TestHabitSlugs:
    """Tests for server-assigned slugs and GET /habits/by-slug/{slug}.

    The slugify/numbering rules themselves are pinned DB-free in test_slugs.py;
    this class covers the habits router's own wiring - including that PUT and
    PATCH both re-slug, since they share `_apply_habit_update`.
    """

    # A COMPLETE body: PUT is a full replace, so an omitted optional field is
    # sent as null and trips the NOT NULL columns.
    HABIT_BODY: ClassVar[dict] = {
        "name": "Daily Stretch",
        "question": "Did you stretch today?",
        "color": "#336699",
        "frequency": 1,
        "range": 1,
        "reminder": False,
        "notes": None,
        "archived": False,
        "sort_order": 0,
    }

    def _body(self, profile_id, **overrides):
        return {**self.HABIT_BODY, "profile_id": profile_id, **overrides}

    async def test_create_assigns_slug_from_name(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        response = await client.post("/habits/", json=self._body(profile.id))
        assert response.status_code == 201
        assert response.json()["slug"] == "daily-stretch"

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
            response = await client.post("/habits/", json=self._body(profile.id))
            assert response.status_code == 201
            slugs.append(response.json()["slug"])

        assert slugs == ["daily-stretch", "daily-stretch-2"]

    async def test_get_by_slug_matches_the_by_id_response(
        self, client, db_session, login_as
    ):
        """Including today's completed/skipped flags - both routes go through
        the same `_habit_to_read`."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        habit = HabitFactory(profile=profile, name="Daily Stretch")
        await db_session.commit()
        TrackerFactory(habit=habit, dated=date.today(), status=TrackerStatus.COMPLETED)
        await db_session.commit()
        habit_id = habit.id

        by_slug = await client.get(
            "/habits/by-slug/daily-stretch", params={"profile_id": profile.id}
        )
        assert by_slug.status_code == 200
        assert by_slug.json()["completed_today"] is True

        by_id = await client.get(f"/habits/{habit_id}")
        assert by_id.json() == by_slug.json()

    async def test_get_by_slug_honours_tz(self, client, db_session, login_as):
        """The tz param reaches the shared read helper, same as the by-id route."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        tz = "Pacific/Kiritimati"
        today_there = datetime.now(ZoneInfo(tz)).date()
        habit = HabitFactory(profile=profile, name="Daily Stretch")
        await db_session.commit()
        TrackerFactory(habit=habit, dated=today_there, status=TrackerStatus.COMPLETED)
        await db_session.commit()

        response = await client.get(
            "/habits/by-slug/daily-stretch",
            params={"profile_id": profile.id, "tz": tz},
        )
        assert response.status_code == 200
        assert response.json()["completed_today"] is True

    async def test_get_by_slug_unknown_slug_404(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/habits/by-slug/nothing-here", params={"profile_id": profile.id}
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

        assert (
            await client.post("/habits/", json=self._body(personal.id))
        ).status_code == 201

        response = await client.get(
            "/habits/by-slug/daily-stretch", params={"profile_id": work.id}
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
            "/habits/by-slug/anything", params={"profile_id": foreign_profile.id}
        )
        assert response.status_code == 403

    async def test_patch_rename_reslugs_and_old_slug_stops_resolving(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post("/habits/", json=self._body(profile.id))
        habit_id = created.json()["id"]

        patched = await client.patch(
            f"/habits/{habit_id}", json={"name": "Evening Walk"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "evening-walk"

        stale = await client.get(
            "/habits/by-slug/daily-stretch", params={"profile_id": profile.id}
        )
        assert stale.status_code == 404
        assert (await client.get(f"/habits/{habit_id}")).status_code == 200

    async def test_put_rename_also_reslugs(self, client, db_session, login_as):
        """PUT goes through the same shared helper, so it must re-slug too."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post("/habits/", json=self._body(profile.id))
        habit_id = created.json()["id"]

        replaced = await client.put(
            f"/habits/{habit_id}",
            json=self._body(profile.id, name="Evening Walk"),
        )
        assert replaced.status_code == 200
        assert replaced.json()["slug"] == "evening-walk"

    async def test_rename_to_same_slug_does_not_bump_itself(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post("/habits/", json=self._body(profile.id))
        patched = await client.patch(
            f"/habits/{created.json()['id']}", json={"name": "  Daily   stretch!  "}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "daily-stretch"

    async def test_patch_without_name_keeps_the_slug(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post("/habits/", json=self._body(profile.id))
        patched = await client.patch(
            f"/habits/{created.json()['id']}", json={"color": "#112233"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "daily-stretch"

    async def test_slug_is_read_only(self, client, db_session, login_as):
        """`slug` is absent from HabitCreate/HabitUpdate, so a client cannot set
        it - the derived slug wins."""
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()
        await login_as(user)

        created = await client.post(
            "/habits/", json=self._body(profile.id, slug="hand-picked")
        )
        assert created.status_code == 201
        assert created.json()["slug"] == "daily-stretch"

        patched = await client.patch(
            f"/habits/{created.json()['id']}", json={"slug": "hand-picked"}
        )
        assert patched.status_code == 200
        assert patched.json()["slug"] == "daily-stretch"


class TestUpdateHabitPut:
    """Tests for PUT /habits/{habit_id} endpoint."""

    async def test_update_own_habit_put(self, client, db_session, login_as):
        """User can update their own habit (full update)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "Updated",
                "question": "Updated question?",
                "color": "#FFFFFF",
                "frequency": 2,
                "range": 3,
                "reminder": True,
                "notes": "Updated notes",
                "archived": False,
                "sort_order": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated"
        assert data["question"] == "Updated question?"

    async def test_update_other_user_habit_put(self, client, db_session, login_as):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "Hacked",
                "question": "Hacked?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
            },
        )
        assert response.status_code == 403

    async def test_update_habit_all_fields_put(self, client, db_session, login_as):
        """Verify all fields are updated."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(
            user=user,
            name="Original",
            question="Original?",
            color="#000000",
            frequency=1,
            range=1,
            reminder=False,
            notes="Original notes",
            archived=False,
            sort_order=0,
        )
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": "New Name",
                "question": "New Question?",
                "color": "#AABBCC",
                "frequency": 5,
                "range": 7,
                "reminder": True,
                "notes": "New notes",
                "archived": True,
                "sort_order": 10,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["question"] == "New Question?"
        assert data["color"] == "#AABBCC"
        assert data["frequency"] == 5
        assert data["range"] == 7
        assert data["reminder"] is True
        assert data["notes"] == "New notes"
        assert data["archived"] is True
        assert data["sort_order"] == 10

    async def test_update_habit_color_put(self, client, db_session, login_as):
        """Update habit color."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, color="#000000")
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": "#FF5733",
                "frequency": habit.frequency,
                "range": habit.range,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": habit.archived,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        assert response.json()["color"] == "#FF5733"

    async def test_update_habit_frequency_range_put(self, client, db_session, login_as):
        """Update frequency and range."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, frequency=1, range=1)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": habit.color,
                "frequency": 5,
                "range": 7,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": habit.archived,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["frequency"] == 5
        assert data["range"] == 7

    async def test_update_habit_archived_put(self, client, db_session, login_as):
        """Archive/unarchive habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, archived=False)
        await db_session.commit()

        await login_as(user)

        # Archive
        response = await client.put(
            f"/habits/{habit.id}",
            json={
                "name": habit.name,
                "question": habit.question,
                "color": habit.color,
                "frequency": habit.frequency,
                "range": habit.range,
                "notes": habit.notes,
                "reminder": habit.reminder,
                "archived": True,
                "sort_order": habit.sort_order,
            },
        )
        assert response.status_code == 200
        assert response.json()["archived"] is True

    async def test_update_nonexistent_habit_put(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/99999",
            json={
                "name": "Test",
                "question": "Test?",
                "color": "#000000",
                "frequency": 1,
                "range": 1,
                "notes": "",
                "reminder": False,
                "archived": False,
                "sort_order": 0,
            },
        )
        assert response.status_code == 404


class TestUpdateHabitPatch:
    """Tests for PATCH /habits/{habit_id} endpoint."""

    async def test_update_habit_single_field_patch(self, client, db_session, login_as):
        """Update only one field."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Patched"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Patched"

    async def test_update_habit_multiple_fields_patch(
        self, client, db_session, login_as
    ):
        """Update multiple fields."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Multi", "question": "Multi question?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Multi"
        assert data["question"] == "Multi question?"

    async def test_update_habit_name_patch(self, client, db_session, login_as):
        """Update habit name."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="Original Name")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_update_habit_question_patch(self, client, db_session, login_as):
        """Update habit question."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"question": "New question?"},
        )
        assert response.status_code == 200
        assert response.json()["question"] == "New question?"

    async def test_update_habit_notes_patch(self, client, db_session, login_as):
        """Update habit notes."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, notes="Original notes")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"notes": "Updated notes"},
        )
        assert response.status_code == 200
        assert response.json()["notes"] == "Updated notes"

    async def test_update_habit_reminder_patch(self, client, db_session, login_as):
        """Toggle reminder setting."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, reminder=False)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"reminder": True},
        )
        assert response.status_code == 200
        assert response.json()["reminder"] is True

    async def test_update_habit_sort_order_patch(self, client, db_session, login_as):
        """Update sort order."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=0)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"sort_order": 50},
        )
        assert response.status_code == 200
        assert response.json()["sort_order"] == 50

    async def test_update_other_user_habit_patch(self, client, db_session, login_as):
        """User cannot update other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.patch(
            f"/habits/{habit.id}",
            json={"name": "Hacked"},
        )
        assert response.status_code == 403


class TestDeleteHabit:
    """Tests for DELETE /habits/{habit_id} endpoint."""

    async def test_delete_own_habit(self, client, db_session, login_as):
        """User can delete their own habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        await login_as(user)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(select(Habit).filter(Habit.id == habit_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_habit(self, client, db_session, login_as):
        """User cannot delete other's habit (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.delete(f"/habits/{habit.id}")
        assert response.status_code == 403

    async def test_delete_habit_as_admin(self, client, db_session, login_as):
        """Admin can delete any habit."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()
        habit_id = habit.id

        await login_as(admin)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

    async def test_delete_nonexistent_habit(self, client, db_session, login_as):
        """Return 404 for non-existent habit."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/habits/99999")
        assert response.status_code == 404

    async def test_delete_habit_cascades_to_trackers(
        self, client, db_session, login_as
    ):
        """Verify trackers are deleted with habit."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        tracker = TrackerFactory(habit=habit)
        await db_session.commit()
        habit_id = habit.id
        tracker_id = tracker.id

        await login_as(user)

        response = await client.delete(f"/habits/{habit_id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Tracker).filter(Tracker.id == tracker_id)
        )
        assert result.scalar_one_or_none() is None


class TestSortHabits:
    """Tests for PUT /habits/sort endpoint."""

    async def test_sort_habits_basic(self, client, db_session, login_as):
        """Successfully reorder multiple habits."""
        user = UserFactory()
        await db_session.commit()

        # Create habits with initial sort orders
        habit1 = HabitFactory(user=user, name="Habit 1")
        habit2 = HabitFactory(user=user, name="Habit 2")
        habit3 = HabitFactory(user=user, name="Habit 3")
        await db_session.commit()

        await login_as(user)

        # Reorder: habit3, habit1, habit2
        response = await client.put(
            "/habits/sort",
            json=[habit3.id, habit1.id, habit2.id],
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Habits sorted successfully"

        # Verify sort_order was updated correctly
        await db_session.refresh(habit1)
        await db_session.refresh(habit2)
        await db_session.refresh(habit3)

        # First ID gets the lowest sort_order (habits display in ascending
        # sort_order): habit3 -> 0, habit1 -> 1, habit2 -> 2
        assert habit3.sort_order == 0
        assert habit1.sort_order == 1
        assert habit2.sort_order == 2

    async def test_sort_habits_archived(self, client, db_session, login_as):
        """Archived habits preserve their sort_order when sorting is applied."""
        user = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user, name="Active Habit", archived=False)
        habit2 = HabitFactory(
            user=user, name="Archived Habit", archived=True, sort_order=5
        )
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/sort",
            json=[habit2.id, habit1.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit1)
        await db_session.refresh(habit2)

        # Only active habits are re-numbered; habit1 is the first (only)
        # active habit in the list so it gets sort_order 0
        assert habit1.sort_order == 0
        # Archived habit preserves its original sort_order
        assert habit2.sort_order == 5

    async def test_sort_habits_archived_preserves_position(
        self, client, db_session, login_as
    ):
        """Archived habits should slot back into their original position when unarchived."""
        user = UserFactory()
        await db_session.commit()

        # Create 4 habits: A, B, C, D with sort_order 3, 2, 1, 0
        habit_a = HabitFactory(user=user, name="A", sort_order=3)
        habit_b = HabitFactory(user=user, name="B", sort_order=2, archived=True)
        habit_c = HabitFactory(user=user, name="C", sort_order=1)
        habit_d = HabitFactory(user=user, name="D", sort_order=0)
        await db_session.commit()

        await login_as(user)

        # Sort only active habits A, C, D (B is archived)
        response = await client.put(
            "/habits/sort",
            json=[habit_a.id, habit_c.id, habit_d.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit_a)
        await db_session.refresh(habit_b)
        await db_session.refresh(habit_c)
        await db_session.refresh(habit_d)

        # Active habits are numbered in request order starting from 0,
        # skipping sort_order values held by archived habits not in the
        # request: A -> 0, C -> 1, D -> 3 (2 is held by archived B).
        # When B is unarchived, ascending order is A(0), C(1), B(2), D(3).
        assert habit_a.sort_order == 0
        assert habit_b.sort_order == 2  # Preserved
        assert habit_c.sort_order == 1
        assert habit_d.sort_order == 3  # Skipped 2

    async def test_sort_habits_single_habit(self, client, db_session, login_as):
        """Sorting a single habit should work."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, sort_order=5)
        await db_session.commit()

        await login_as(user)

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 200

        await db_session.refresh(habit)
        assert habit.sort_order == 0

    async def test_sort_habits_empty_list(self, client, db_session, login_as):
        """Sorting empty list returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[])
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"].lower()

    async def test_sort_habits_duplicate_ids(self, client, db_session, login_as):
        """Sorting with duplicate habit IDs returns 400 Bad Request."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[habit.id, habit.id])
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    async def test_sort_habits_not_found(self, client, db_session, login_as):
        """Cannot sort non-existent habit (404)."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[99999])
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_sort_habits_unauthorized(self, client, db_session, login_as):
        """User cannot sort other user's habits (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 403

    async def test_sort_habits_mixed_ownership(self, client, db_session, login_as):
        """Cannot sort habits when some belong to other users (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user1)
        habit2 = HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.put(
            "/habits/sort",
            json=[
                habit1.id,
                habit2.id,
            ],
        )
        assert response.status_code == 403

    async def test_sort_habits_unauthenticated(self, client, db_session):
        """Unauthenticated users cannot sort habits (401)."""
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user)
        await db_session.commit()

        response = await client.put(
            "/habits/sort",
            json=[habit.id],
        )
        assert response.status_code == 401


class TestSortHabitsProfileScoping:
    """sort_habits computes archived gaps per profile, not per user."""

    async def test_archived_gap_ignores_other_profiles(
        self, client, db_session, login_as
    ):
        """An archived habit in ANOTHER profile does not shift sort_order.

        Before profile scoping, the archived habit's sort_order was treated as
        a taken slot for every one of the user's habits. Now only the sorted
        profile's archived habits reserve slots.
        """
        user = UserFactory()
        await db_session.commit()

        other_profile = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        HabitFactory(
            user=user,
            name="Archived Elsewhere",
            profile=other_profile,
            archived=True,
            sort_order=0,
        )
        first = HabitFactory(user=user, name="First", sort_order=5)
        second = HabitFactory(user=user, name="Second", sort_order=6)
        await db_session.commit()
        # Capture ids before expire_all() below - expire_all() expires the
        # instances' id attribute too, so accessing first.id/second.id after
        # it would trigger a synchronous lazy-reload outside async context.
        first_id, second_id = first.id, second.id

        await login_as(user)

        response = await client.put("/habits/sort", json=[first_id, second_id])
        assert response.status_code == 200

        db_session.expire_all()
        assert (await db_session.get(Habit, first_id)).sort_order == 0
        assert (await db_session.get(Habit, second_id)).sort_order == 1

    async def test_archived_gap_respected_within_profile(
        self, client, db_session, login_as
    ):
        """An archived habit in the SAME profile still reserves its slot."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user, name="Archived Here", archived=True, sort_order=0)
        first = HabitFactory(user=user, name="First", sort_order=5)
        second = HabitFactory(user=user, name="Second", sort_order=6)
        await db_session.commit()
        # Capture ids before expire_all() below - see comment in
        # test_archived_gap_ignores_other_profiles.
        first_id, second_id = first.id, second.id

        await login_as(user)

        response = await client.put("/habits/sort", json=[first_id, second_id])
        assert response.status_code == 200

        db_session.expire_all()
        assert (await db_session.get(Habit, first_id)).sort_order == 1
        assert (await db_session.get(Habit, second_id)).sort_order == 2

    async def test_sort_foreign_habit_forbidden(self, client, db_session, login_as):
        """A habit in someone else's profile is a 403, not a silent reorder."""
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()

        mine = HabitFactory(user=user)
        theirs = HabitFactory(user=other)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[mine.id, theirs.id])
        assert response.status_code == 403

    async def test_sort_unknown_habit_not_found(self, client, db_session, login_as):
        """An id that does not exist at all is a 404."""
        user = UserFactory()
        await db_session.commit()
        mine = HabitFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[mine.id, 999999])
        assert response.status_code == 404

    async def test_sort_mixed_errors_reports_not_found_first(
        self, client, db_session, login_as
    ):
        """A nonexistent id wins over a foreign one: 404, not 403.

        Missing rows are rejected before any profile is authorized, so a batch
        containing both an unknown id and another user's habit reports the
        unknown id. This deliberately differs from the pre-profile-scoping
        behaviour, which returned 403 whenever any unrecognised id existed
        somewhere; it matches sort_tasks and reveals less to the caller.
        """
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()

        mine = HabitFactory(user=user)
        theirs = HabitFactory(user=other)
        await db_session.commit()

        await login_as(user)

        response = await client.put("/habits/sort", json=[mine.id, theirs.id, 999999])
        assert response.status_code == 404


class TestDeleteAllHabits:
    """Tests for DELETE /habits/ (bulk delete, profile-scoped)."""

    async def test_deletes_habits_and_trackers_only_this_profile(
        self, client, db_session, login_as
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

        await login_as(user)
        response = await client.delete("/habits/", params={"profile_id": profile.id})
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Habit))).scalars().all()
        assert [h.id for h in remaining] == [keep.id]
        # Trackers of the deleted habits are gone too (expire first so the
        # check re-reads from the DB rather than the session identity map).
        db_session.expire_all()
        assert await db_session.get(Tracker, tracker_id) is None


class TestListHabits:
    """Tests for GET /habits/ (profile-scoped habit listing)."""

    async def test_list_habits_in_own_profile(self, client, db_session, login_as):
        """Owner can list the habits in their profile."""
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user, name="Habit 1")
        HabitFactory(user=user, name="Habit 2")
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["habits"]) == 2

    async def test_list_habits_requires_profile_id(self, client, db_session, login_as):
        """profile_id is required (422 when omitted)."""
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get("/habits/")
        assert response.status_code == 422

    async def test_list_habits_foreign_profile_forbidden(
        self, client, db_session, login_as
    ):
        """Regular user cannot list another user's profile (403)."""
        user1 = UserFactory()
        user2 = UserFactory()
        await db_session.commit()

        HabitFactory(user=user2)
        await db_session.commit()

        await login_as(user1)

        response = await client.get(
            "/habits/", params={"profile_id": user2.profiles[0].id}
        )
        assert response.status_code == 403

    async def test_list_habits_unknown_profile(self, client, db_session, login_as):
        """Unknown profile_id is a 404."""
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get("/habits/", params={"profile_id": 999999})
        assert response.status_code == 404

    async def test_list_habits_as_admin(self, client, db_session, login_as):
        """Admin can list any profile's habits."""
        admin = AdminUserFactory()
        user = UserFactory()
        await db_session.commit()

        HabitFactory(user=user, name="User Habit")
        await db_session.commit()

        await login_as(admin)

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_list_habits_only_that_profile(self, client, db_session, login_as):
        """Habits from the user's other profiles are excluded."""
        user = UserFactory()
        await db_session.commit()

        other_profile = ProfileFactory(user=user, name="Work")
        await db_session.commit()

        HabitFactory(user=user, name="Personal Habit")
        mine = HabitFactory(user=user, name="Work Habit", profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/habits/", params={"profile_id": other_profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [h["id"] for h in data["habits"]] == [mine.id]

    async def test_list_habits_pagination(self, client, db_session, login_as):
        """limit caps the page; total reports the full count; results are the
        first `limit` habits by sort_order."""
        user = UserFactory()
        await db_session.commit()

        # Descending sort_order so heap/insertion order disagrees with the
        # expected (ascending sort_order) order - this would fail if the
        # order_by were removed.
        habits = [
            HabitFactory(user=user, name=f"Habit {i}", sort_order=9 - i)
            for i in range(10)
        ]
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id, "limit": 3}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["habits"]) == 3
        assert data["total"] == 10
        assert data["limit"] == 3
        expected_ids = [h.id for h in sorted(habits, key=lambda h: h.sort_order)[:3]]
        assert [h["id"] for h in data["habits"]] == expected_ids

    async def test_list_habits_includes_today_status(
        self, client, db_session, login_as
    ):
        """completed_today and skipped_today reflect today's tracker."""
        user = UserFactory()
        await db_session.commit()

        habit1 = HabitFactory(user=user, name="Completed Habit")
        habit2 = HabitFactory(user=user, name="Skipped Habit")
        HabitFactory(user=user, name="No Tracker Habit")
        await db_session.commit()

        TrackerFactory(habit=habit1, dated=date.today(), status=TrackerStatus.COMPLETED)
        TrackerFactory(habit=habit2, dated=date.today(), status=TrackerStatus.SKIPPED)
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 200
        habits_by_name = {h["name"]: h for h in response.json()["habits"]}

        assert habits_by_name["Completed Habit"]["completed_today"] is True
        assert habits_by_name["Completed Habit"]["skipped_today"] is False
        assert habits_by_name["Skipped Habit"]["completed_today"] is False
        assert habits_by_name["Skipped Habit"]["skipped_today"] is True
        assert habits_by_name["No Tracker Habit"]["completed_today"] is False
        assert habits_by_name["No Tracker Habit"]["skipped_today"] is False

    async def test_list_habits_today_status_honors_tz(
        self, client, db_session, login_as
    ):
        """completed_today is computed against "today" in the requested zone.

        Etc/GMT+12 (UTC-12) and Etc/GMT-14 (UTC+14) are 26 hours apart, so
        their calendar dates always differ. A tracker dated "today" in one
        zone is therefore completed_today only for that zone, regardless of
        when the test runs.
        """
        user = UserFactory()
        await db_session.commit()

        habit = HabitFactory(user=user, name="TZ Habit")
        await db_session.commit()

        tz_name, other_tz_name = "Etc/GMT+12", "Etc/GMT-14"
        expected_today = datetime.now(ZoneInfo(tz_name)).date()
        TrackerFactory(
            habit=habit, dated=expected_today, status=TrackerStatus.COMPLETED
        )
        await db_session.commit()

        await login_as(user)
        profile_id = user.profiles[0].id

        response = await client.get(
            "/habits/", params={"profile_id": profile_id, "tz": tz_name}
        )
        assert response.status_code == 200
        assert response.json()["habits"][0]["completed_today"] is True

        response = await client.get(
            "/habits/", params={"profile_id": profile_id, "tz": other_tz_name}
        )
        assert response.status_code == 200
        assert response.json()["habits"][0]["completed_today"] is False

    async def test_list_habits_invalid_tz(self, client, db_session, login_as):
        """Invalid tz name is rejected with 422, not a server error."""
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/habits/",
            params={"profile_id": user.profiles[0].id, "tz": "Not/AZone"},
        )
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    async def test_list_habits_empty(self, client, db_session, login_as):
        """A profile with no habits returns an empty list."""
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.get(
            "/habits/", params={"profile_id": user.profiles[0].id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["habits"] == []
