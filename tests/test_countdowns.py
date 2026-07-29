"""Tests for countdown management endpoints."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from habit_tracker.schemas.db_models import Countdown
from tests.factories import (
    CountdownFactory,
    ProfileFactory,
    TaskFactory,
    UserFactory,
)


class TestListCountdowns:
    """Tests for GET /countdowns/ endpoint."""

    async def test_list_countdowns_requires_profile_id(
        self, client, db_session, login_as
    ):
        """profile_id query parameter is required (422 if missing)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/")
        assert response.status_code == 422

    async def test_list_countdowns_unknown_profile(self, client, db_session, login_as):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/", params={"profile_id": 99999})
        assert response.status_code == 404

    async def test_list_countdowns_foreign_profile(self, client, db_session, login_as):
        """Cannot list countdowns of another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/", params={"profile_id": foreign.id})
        assert response.status_code == 403

    async def test_list_countdowns_scoped_to_profile(
        self, client, db_session, login_as
    ):
        """Only countdowns of the requested profile are returned."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        c1 = CountdownFactory(profile=profile)
        c2 = CountdownFactory(profile=profile)
        CountdownFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {c["id"] for c in data["countdowns"]}
        assert ids == {c1.id, c2.id}

    async def test_list_countdowns_ordered_by_target_date(
        self, client, db_session, login_as
    ):
        """Countdowns come back soonest target first."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        today = date.today()
        later = CountdownFactory(
            profile=profile, title="Later", target_date=today + timedelta(days=30)
        )
        soonest = CountdownFactory(
            profile=profile, title="Soonest", target_date=today + timedelta(days=1)
        )
        middle = CountdownFactory(
            profile=profile, title="Middle", target_date=today + timedelta(days=10)
        )
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/", params={"profile_id": profile.id})
        assert response.status_code == 200
        ids = [c["id"] for c in response.json()["countdowns"]]
        assert ids == [soonest.id, middle.id, later.id]

    async def test_list_countdowns_pagination(self, client, db_session, login_as):
        """limit/offset paginate the result and total reflects the full count."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        for i in range(5):
            CountdownFactory(
                profile=profile, target_date=date.today() + timedelta(days=i)
            )
        await db_session.commit()

        await login_as(user)

        response = await client.get(
            "/countdowns/", params={"profile_id": profile.id, "limit": 2, "offset": 1}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 1
        assert len(data["countdowns"]) == 2


class TestCreateCountdown:
    """Tests for POST /countdowns/ endpoint."""

    async def test_create_countdown_basic(self, client, db_session, login_as):
        """Create a standalone countdown (no task link)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Launch day",
                "target_date": "2026-12-25",
                "color": "#AA00BB",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["profile_id"] == profile.id
        assert data["title"] == "Launch day"
        assert data["target_date"] == "2026-12-25"
        assert data["color"] == "#AA00BB"
        assert data["task_id"] is None
        assert data["repeat"] == "none"
        assert data["show_occurrence"] is False

    async def test_create_countdown_foreign_profile(self, client, db_session, login_as):
        """Cannot create a countdown in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": foreign.id,
                "title": "Nope",
                "target_date": "2026-12-25",
            },
        )
        assert response.status_code == 403

    async def test_create_countdown_unknown_profile(self, client, db_session, login_as):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={"profile_id": 99999, "title": "Nope", "target_date": "2026-12-25"},
        )
        assert response.status_code == 404

    async def test_create_countdown_with_task_link(self, client, db_session, login_as):
        """A countdown can link a task in the same profile."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Ship it",
                "target_date": "2026-12-25",
                "task_id": task.id,
            },
        )
        assert response.status_code == 201
        assert response.json()["task_id"] == task.id

    async def test_create_countdown_task_in_other_profile_rejected(
        self, client, db_session, login_as
    ):
        """Linking a task from a different profile is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        task = TaskFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Mismatched",
                "target_date": "2026-12-25",
                "task_id": task.id,
            },
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Linked task not found or belongs to a different profile"
        )

    async def test_create_countdown_unknown_task_rejected(
        self, client, db_session, login_as
    ):
        """Linking a non-existent task is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Ghost task",
                "target_date": "2026-12-25",
                "task_id": 99999,
            },
        )
        assert response.status_code == 400

    async def test_create_countdown_invalid_color(self, client, db_session, login_as):
        """Invalid color is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Bad color",
                "target_date": "2026-12-25",
                "color": "blue",
            },
        )
        assert response.status_code == 422

    async def test_create_countdown_invalid_repeat(self, client, db_session, login_as):
        """An unrecognized repeat value is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Bad repeat",
                "target_date": "2026-12-25",
                "repeat": "daily",
            },
        )
        assert response.status_code == 422

    async def test_create_countdown_blank_title_rejected(
        self, client, db_session, login_as
    ):
        """A blank/whitespace-only title is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "   ",
                "target_date": "2026-12-25",
            },
        )
        assert response.status_code == 422

    async def test_create_countdown_each_valid_repeat_value(
        self, client, db_session, login_as
    ):
        """Every documented repeat value is accepted."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        for repeat in ("none", "weekly", "monthly", "monthly_weekday", "yearly"):
            response = await client.post(
                "/countdowns/",
                json={
                    "profile_id": profile.id,
                    "title": f"Repeats {repeat}",
                    "target_date": "2026-12-25",
                    "repeat": repeat,
                },
            )
            assert response.status_code == 201, repeat
            assert response.json()["repeat"] == repeat

    async def test_create_countdown_show_occurrence(self, client, db_session, login_as):
        """show_occurrence is accepted and echoed back."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "26th birthday",
                "target_date": "2026-12-25",
                "repeat": "yearly",
                "show_occurrence": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["show_occurrence"] is True


class TestGetCountdown:
    """Tests for GET /countdowns/{countdown_id} endpoint."""

    async def test_get_own_countdown(self, client, db_session, login_as):
        """User can retrieve their own countdown."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, title="My Countdown")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/countdowns/{countdown.id}")
        assert response.status_code == 200
        assert response.json()["title"] == "My Countdown"

    async def test_get_nonexistent_countdown(self, client, db_session, login_as):
        """Return 404 for non-existent countdown."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdowns/99999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Countdown not found"

    async def test_get_other_user_countdown(self, client, db_session, login_as):
        """User cannot access a countdown in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        countdown = CountdownFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/countdowns/{countdown.id}")
        assert response.status_code == 403


class TestPatchCountdown:
    """Tests for PATCH /countdowns/{countdown_id} endpoint."""

    async def test_patch_countdown_rename(self, client, db_session, login_as):
        """Rename a countdown."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, title="Old Name")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"title": "New Name"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "New Name"

    async def test_patch_countdown_stamps_updated_date(
        self, client, db_session, login_as
    ):
        """updated_date is server-stamped on every patch, never client-set."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, updated_date=None)
        await db_session.commit()
        assert countdown.updated_date is None

        await login_as(user)

        before = datetime.now()
        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"title": "Touched"}
        )
        assert response.status_code == 200

        await db_session.refresh(countdown)
        assert countdown.updated_date is not None
        assert countdown.updated_date >= before

    async def test_patch_countdown_updated_date_not_client_settable(
        self, client, db_session, login_as
    ):
        """A client-supplied updated_date is not part of the update schema."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}",
            json={"title": "Touched", "updated_date": "2020-01-01T00:00:00"},
        )
        assert response.status_code == 200
        # Server stamp is "now", nowhere near the rejected client value.
        assert not response.json()["updated_date"].startswith("2020-01-01")

    async def test_patch_countdown_null_title_rejected(
        self, client, db_session, login_as
    ):
        """An explicit null for the non-nullable title is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"title": None}
        )
        assert response.status_code == 422

    async def test_patch_countdown_move_to_own_profile(
        self, client, db_session, login_as
    ):
        """Move a countdown to another profile of the same user."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 200
        assert response.json()["profile_id"] == other_profile.id

    async def test_patch_countdown_task_link_revalidated_on_profile_change(
        self, client, db_session, login_as
    ):
        """Moving profiles re-validates the existing task link against the
        NEW profile - a task that belonged to the old profile no longer
        matches, so the move is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        task = TaskFactory(profile=profile)
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, task=task)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"profile_id": other_profile.id}
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Linked task not found or belongs to a different profile"
        )

    async def test_patch_countdown_task_link_revalidated_on_new_task_id(
        self, client, db_session, login_as
    ):
        """Setting task_id to a task in a different profile is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        foreign_task = TaskFactory(profile=other_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"task_id": foreign_task.id}
        )
        assert response.status_code == 400

    async def test_patch_other_user_countdown(self, client, db_session, login_as):
        """User cannot patch a countdown in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        countdown = CountdownFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"title": "Hacked"}
        )
        assert response.status_code == 403

    async def test_patch_nonexistent_countdown(self, client, db_session, login_as):
        """Return 404 for non-existent countdown."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.patch("/countdowns/99999", json={"title": "Nope"})
        assert response.status_code == 404


class TestDeleteCountdown:
    """Tests for DELETE /countdowns/{countdown_id} endpoint."""

    async def test_delete_own_countdown(self, client, db_session, login_as):
        """User can delete their own countdown."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.delete(f"/countdowns/{countdown_id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(Countdown).filter(Countdown.id == countdown_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_countdown(self, client, db_session, login_as):
        """User cannot delete a countdown in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        countdown = CountdownFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(user)

        response = await client.delete(f"/countdowns/{countdown.id}")
        assert response.status_code == 403

    async def test_delete_nonexistent_countdown(self, client, db_session, login_as):
        """Return 404 for non-existent countdown."""
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.delete("/countdowns/99999")
        assert response.status_code == 404


class TestDeleteAllCountdowns:
    """Tests for DELETE /countdowns/ (bulk delete, profile-scoped)."""

    async def test_deletes_only_this_profile(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        CountdownFactory(profile=profile, title="A")
        CountdownFactory(profile=profile, title="B")
        CountdownFactory(profile=other, title="Keep")
        await db_session.commit()

        await login_as(user)
        response = await client.delete(
            "/countdowns/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        remaining = (await db_session.execute(select(Countdown))).scalars().all()
        assert [c.title for c in remaining] == ["Keep"]
