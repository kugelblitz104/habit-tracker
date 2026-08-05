"""Tests for countdown management endpoints."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from habit_tracker.schemas.db_models import Countdown, CountdownCategory
from tests.factories import (
    CountdownCategoryFactory,
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

    async def test_patch_countdown_move_to_another_users_profile(
        self, client, db_session, login_as
    ):
        """A move to a profile owned by a different user is rejected (400),
        the countdown stays put, and nothing is written into the other user's
        profile - a category resolved against the destination would otherwise
        insert a named, coloured group there."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Mine")
        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, category="Bills")
        await db_session.commit()
        countdown_id = countdown.id
        profile_id = profile.id
        foreign_profile_id = foreign_profile.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"profile_id": foreign_profile_id}
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "New profile not found or does not belong to the same user"
        )

        db_session.expire_all()
        unchanged = await db_session.get(Countdown, countdown_id)
        assert unchanged.profile_id == profile_id

        foreign_categories = (
            (
                await db_session.execute(
                    select(CountdownCategory).where(
                        CountdownCategory.profile_id == foreign_profile_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert foreign_categories == []

    async def test_patch_countdown_move_to_nonexistent_profile(
        self, client, db_session, login_as
    ):
        """A move to a profile that does not exist is rejected (400)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Mine")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile)
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown.id}", json={"profile_id": 99999}
        )
        assert response.status_code == 400

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


class TestCountdownCategoryById:
    """Tests for selecting a category by explicit `category_id` on create/patch."""

    async def test_create_with_category_id_sets_the_mirror(
        self, client, db_session, login_as
    ):
        """An explicit id fills `category` from the record's own name."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        category = CountdownCategoryFactory(
            profile=profile, name="Bills", color="#0EA5E9"
        )
        await db_session.commit()
        category_id = category.id

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category_id": category_id,
            },
        )
        assert response.status_code == 201
        assert response.json()["category"] == "Bills"
        assert response.json()["category_id"] == category_id

    async def test_category_id_wins_over_free_text(self, client, db_session, login_as):
        """Sending both uses the id and overwrites the text from the record."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()
        category_id = category.id

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "Birthdays",
                "category_id": category_id,
            },
        )
        assert response.status_code == 201
        assert response.json()["category"] == "Bills"
        assert response.json()["category_id"] == category_id

        # The losing free-text name must not have created a second group.
        result = await db_session.execute(
            select(CountdownCategory).where(CountdownCategory.profile_id == profile.id)
        )
        assert [c.name for c in result.scalars().all()] == ["Bills"]

    async def test_create_with_another_profiles_category_is_400(
        self, client, db_session, login_as
    ):
        """A category in a profile the countdown does not belong to is rejected."""
        user = UserFactory()
        await db_session.commit()

        mine = ProfileFactory(user=user, name="Mine")
        other = ProfileFactory(user=user, name="Other")
        await db_session.commit()

        foreign = CountdownCategoryFactory(profile=other, name="Bills")
        await db_session.commit()
        foreign_id = foreign.id

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": mine.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category_id": foreign_id,
            },
        )
        assert response.status_code == 400

    async def test_create_with_a_missing_category_id_is_400(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category_id": 999999,
            },
        )
        assert response.status_code == 400

    async def test_patch_relinks_by_category_id(self, client, db_session, login_as):
        """Selecting a different group by id moves the countdown and the mirror."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, title="Julianna", category="Birthdays"
        )
        birthday = CountdownCategoryFactory(
            profile=profile, name="Birthday", color="#0EEC63"
        )
        await db_session.commit()
        countdown_id = countdown.id
        birthday_id = birthday.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"category_id": birthday_id}
        )
        assert response.status_code == 200
        assert response.json()["category"] == "Birthday"
        assert response.json()["category_id"] == birthday_id

    async def test_patch_category_id_to_null_clears_both(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, title="Rent", category="Bills", category_id=category.id
        )
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"category_id": None}
        )
        assert response.status_code == 200
        assert response.json()["category"] is None
        assert response.json()["category_id"] is None


class TestCountdownCategoryLink:
    """Tests for resolving `category` to `category_id` on create/patch."""

    async def test_create_with_a_category_creates_the_record(
        self, client, db_session, login_as
    ):
        """A new category name on create resolves and creates a category row."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "Bills",
            },
        )
        assert response.status_code == 201

        db_session.expire_all()
        countdown = await db_session.get(Countdown, response.json()["id"])
        assert countdown is not None
        assert countdown.category == "Bills"
        assert countdown.category_id is not None

    async def test_create_seeds_the_category_color_from_the_countdown(
        self, client, db_session, login_as
    ):
        """The first countdown in a new group seeds the group's colour."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "Bills",
                "color": "#0EA5E9",
            },
        )
        assert response.status_code == 201

        db_session.expire_all()
        countdown = await db_session.get(Countdown, response.json()["id"])
        category = await db_session.get(CountdownCategory, countdown.category_id)
        assert category is not None
        assert category.color == "#0EA5E9"

    async def test_second_countdown_does_not_repaint_the_group(
        self, client, db_session, login_as
    ):
        """A second countdown joining an existing group keeps the group's
        colour as-is, while its own colour override is unaffected."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        first = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "Bills",
                "color": "#0EA5E9",
            },
        )
        assert first.status_code == 201

        second = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Electric",
                "target_date": "2026-09-05",
                "category": "Bills",
                "color": "#FF0000",
            },
        )
        assert second.status_code == 201
        assert second.json()["color"] == "#FF0000"

        categories = (
            (await db_session.execute(select(CountdownCategory))).scalars().all()
        )
        assert len(categories) == 1
        assert categories[0].color == "#0EA5E9"

    async def test_create_trims_the_category_name(self, client, db_session, login_as):
        """Leading/trailing whitespace in the category name is trimmed."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "  Bills  ",
            },
        )
        assert response.status_code == 201

        db_session.expire_all()
        countdown = await db_session.get(Countdown, response.json()["id"])
        assert countdown.category == "Bills"

    async def test_patch_to_a_new_category_relinks(self, client, db_session, login_as):
        """Patching to a different category name re-resolves category_id
        against the new name."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, category="Bills", category_id=category.id
        )
        await db_session.commit()
        countdown_id = countdown.id
        old_category_id = category.id
        profile_id = profile.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"category": "Birthdays"}
        )
        assert response.status_code == 200
        assert response.json()["category"] == "Birthdays"

        db_session.expire_all()
        updated = await db_session.get(Countdown, countdown_id)
        assert updated.category == "Birthdays"
        assert updated.category_id is not None
        assert updated.category_id != old_category_id

        birthdays = await db_session.get(CountdownCategory, updated.category_id)
        assert birthdays.name == "Birthdays"
        assert birthdays.profile_id == profile_id

    async def test_patch_category_to_null_clears_both(
        self, client, db_session, login_as
    ):
        """Patching category to null clears both category and category_id."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, category="Bills", category_id=category.id
        )
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"category": None}
        )
        assert response.status_code == 200
        assert response.json()["category"] is None

        db_session.expire_all()
        updated = await db_session.get(Countdown, countdown_id)
        assert updated.category is None
        assert updated.category_id is None

    async def test_profile_move_reresolves_the_category(
        self, client, db_session, login_as
    ):
        """Moving a countdown to another profile re-resolves its category
        against the destination profile: a category belongs to exactly one
        profile, so keeping the old category_id would point the countdown at
        a record in a profile it no longer belongs to."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, category="Bills", category_id=category.id
        )
        await db_session.commit()
        countdown_id = countdown.id
        old_category_id = category.id
        other_profile_id = other_profile.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"profile_id": other_profile_id}
        )
        assert response.status_code == 200
        assert response.json()["category"] == "Bills"

        db_session.expire_all()
        updated = await db_session.get(Countdown, countdown_id)
        assert updated.profile_id == other_profile_id
        assert updated.category == "Bills"
        assert updated.category_id is not None
        assert updated.category_id != old_category_id

        new_category = await db_session.get(CountdownCategory, updated.category_id)
        assert new_category is not None
        assert new_category.profile_id == other_profile_id
        assert new_category.name == "Bills"

    async def test_response_body_exposes_category_id(
        self, client, db_session, login_as
    ):
        """category_id is returned on create, patch and read, so a client joins
        countdowns to their categories by id rather than by the mutable name."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        create_response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
                "category": "Bills",
            },
        )
        assert create_response.status_code == 201
        countdown_id = create_response.json()["id"]

        db_session.expire_all()
        countdown = await db_session.get(Countdown, countdown_id)
        bills_id = countdown.category_id
        assert bills_id is not None
        assert create_response.json()["category_id"] == bills_id

        patch_response = await client.patch(
            f"/countdowns/{countdown_id}", json={"category": "Birthdays"}
        )
        assert patch_response.status_code == 200
        birthdays_id = patch_response.json()["category_id"]
        assert birthdays_id is not None
        assert birthdays_id != bills_id

        read_response = await client.get(f"/countdowns/{countdown_id}")
        assert read_response.status_code == 200
        assert read_response.json()["category_id"] == birthdays_id

        birthdays = await db_session.get(CountdownCategory, birthdays_id)
        assert birthdays.name == "Birthdays"

    async def test_category_id_is_null_when_uncategorised(
        self, client, db_session, login_as
    ):
        """A countdown with no category reports category_id as null."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Rent",
                "target_date": "2026-09-01",
            },
        )
        assert response.status_code == 201
        assert response.json()["category_id"] is None

    async def test_patch_by_name_leaves_an_unsent_category_id_alone(
        self, client, db_session, login_as
    ):
        """A patch that touches neither field keeps the existing link."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        bills = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(
            profile=profile, category="Bills", category_id=bills.id
        )
        await db_session.commit()
        countdown_id = countdown.id
        bills_id = bills.id

        await login_as(user)

        response = await client.patch(
            f"/countdowns/{countdown_id}", json={"title": "Rent due"}
        )
        assert response.status_code == 200
        assert response.json()["category_id"] == bills_id

        db_session.expire_all()
        updated = await db_session.get(Countdown, countdown_id)
        assert updated.category_id == bills_id
        assert updated.category == "Bills"
