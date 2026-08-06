"""Countdown category CRUD, ownership, and the find-or-create rule.

Rejection of bad input lives in test_validation.py; this file covers the
entity's own behaviour and its router.
"""

import pytest
from sqlalchemy import select

from habit_tracker.models import CountdownCategoryCreate, CountdownCategoryUpdate
from habit_tracker.schemas.db_models import Countdown, CountdownCategory
from habit_tracker.services.countdown_categories import (
    find_or_create,
    resolve_for_countdown,
)
from tests.factories import (
    CountdownCategoryFactory,
    CountdownFactory,
    ProfileFactory,
    UserFactory,
)


class TestCountdownCategoryModels:
    def test_color_is_optional(self):
        model = CountdownCategoryCreate(profile_id=1, name="Bills")
        assert model.color is None

    def test_valid_hex_color_accepted(self):
        model = CountdownCategoryCreate(profile_id=1, name="Bills", color="#0EA5E9")
        assert model.color == "#0EA5E9"

    def test_invalid_hex_color_rejected(self):
        with pytest.raises(ValueError, match="valid hex code"):
            CountdownCategoryCreate(profile_id=1, name="Bills", color="teal")

    def test_blank_name_rejected(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            CountdownCategoryCreate(profile_id=1, name="   ")

    def test_name_is_trimmed(self):
        assert CountdownCategoryCreate(profile_id=1, name="  Bills  ").name == "Bills"

    def test_update_name_is_trimmed(self):
        assert CountdownCategoryUpdate(name="  Bills  ").name == "Bills"

    def test_update_blank_name_rejected(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            CountdownCategoryUpdate(name="   ")

    def test_update_rejects_explicit_null_name(self):
        with pytest.raises(ValueError, match="cannot be null"):
            CountdownCategoryUpdate(name=None)

    def test_update_allows_explicit_null_color(self):
        assert CountdownCategoryUpdate(color=None).color is None


class TestFindOrCreate:
    async def test_creates_when_absent(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        row = await find_or_create(db_session, profile_id=profile.id, name="Bills")

        assert row.id is not None
        assert row.name == "Bills"
        assert row.color is None

    async def test_returns_existing_without_duplicating(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        first = await find_or_create(db_session, profile_id=profile.id, name="Bills")
        second = await find_or_create(db_session, profile_id=profile.id, name="Bills")

        assert first.id == second.id
        result = await db_session.execute(
            select(CountdownCategory).where(CountdownCategory.profile_id == profile.id)
        )
        assert len(result.scalars().all()) == 1

    async def test_name_is_trimmed(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        row = await find_or_create(db_session, profile_id=profile.id, name="  Bills  ")

        assert row.name == "Bills"

    async def test_matching_is_case_sensitive(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        upper = await find_or_create(db_session, profile_id=profile.id, name="Bills")
        lower = await find_or_create(db_session, profile_id=profile.id, name="bills")

        assert upper.id != lower.id

    async def test_same_name_in_two_profiles_is_two_records(self, db_session):
        user_one, user_two = UserFactory(), UserFactory()
        await db_session.commit()

        one = ProfileFactory(user=user_one)
        two = ProfileFactory(user=user_two)
        await db_session.commit()

        a = await find_or_create(db_session, profile_id=one.id, name="Bills")
        b = await find_or_create(db_session, profile_id=two.id, name="Bills")

        assert a.id != b.id


class TestResolveForCountdown:
    async def test_none_name_clears(self, db_session):
        assert await resolve_for_countdown(db_session, profile_id=1, name=None) is None

    async def test_blank_name_clears(self, db_session):
        assert await resolve_for_countdown(db_session, profile_id=1, name="   ") is None

    async def test_returns_the_trimmed_categorys_id(self, db_session):
        """The name is trimmed before matching/creating, same as `find_or_create`."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category_id = await resolve_for_countdown(
            db_session, profile_id=profile.id, name=" Bills "
        )

        row = await db_session.get(CountdownCategory, category_id)
        assert row is not None and row.name == "Bills"


class TestCountdownCategoryRouter:
    """Tests for the /countdown-categories/ CRUD router."""

    async def test_create_returns_201_with_the_record(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        await login_as(user)

        response = await client.post(
            "/countdown-categories/",
            json={"profile_id": profile.id, "name": "Bills", "color": "#0EA5E9"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Bills"
        assert body["color"] == "#0EA5E9"
        assert body["id"] is not None

    async def test_create_stores_the_trimmed_name(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()
        profile_id = profile.id

        await login_as(user)

        response = await client.post(
            "/countdown-categories/",
            json={"profile_id": profile_id, "name": "  Bills  "},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Bills"

        db_session.expire_all()
        stored = await db_session.get(CountdownCategory, response.json()["id"])
        assert stored.name == "Bills"

    async def test_patch_stores_the_trimmed_name(self, client, db_session, login_as):
        """Renaming a category doesn't disturb its members' `category_id` link."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()
        category_id = category.id

        countdown = CountdownFactory(profile=profile, category_id=category_id)
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.patch(
            f"/countdown-categories/{category_id}", json={"name": "  Utilities  "}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Utilities"

        db_session.expire_all()
        stored = await db_session.get(CountdownCategory, category_id)
        assert stored.name == "Utilities"
        member = await db_session.get(Countdown, countdown_id)
        assert member.category_id == category_id

    async def test_whitespace_only_name_is_rejected(self, client, db_session, login_as):
        """Trimming does not weaken the blank check on either write path."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        await login_as(user)

        create_response = await client.post(
            "/countdown-categories/",
            json={"profile_id": profile.id, "name": "   "},
        )
        assert create_response.status_code == 422

        patch_response = await client.patch(
            f"/countdown-categories/{category.id}", json={"name": "   "}
        )
        assert patch_response.status_code == 422

    async def test_duplicate_name_in_one_profile_is_409(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        await login_as(user)
        payload = {"profile_id": profile.id, "name": "Bills"}
        await client.post("/countdown-categories/", json=payload)

        response = await client.post("/countdown-categories/", json=payload)

        assert response.status_code == 409

    async def test_list_is_ordered_by_name(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        for name in ("Zebra", "Apples", "Milk"):
            CountdownCategoryFactory(profile=profile, name=name)
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/countdown-categories/?profile_id={profile.id}")

        assert response.status_code == 200
        body = response.json()
        assert [c["name"] for c in body["categories"]] == ["Apples", "Milk", "Zebra"]
        assert body["total"] == 3

    async def test_list_includes_categories_with_no_countdowns(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        CountdownCategoryFactory(profile=profile, name="Empty")
        await db_session.commit()

        await login_as(user)

        response = await client.get(f"/countdown-categories/?profile_id={profile.id}")

        assert [c["name"] for c in response.json()["categories"]] == ["Empty"]

    async def test_patch_updates_color(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdown-categories/{category.id}", json={"color": "#123456"}
        )

        assert response.status_code == 200
        assert response.json()["color"] == "#123456"

    async def test_patch_can_clear_the_color(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(
            profile=profile, name="Bills", color="#0EA5E9"
        )
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdown-categories/{category.id}", json={"color": None}
        )

        assert response.status_code == 200
        assert response.json()["color"] is None

    async def test_patch_to_a_taken_name_is_409(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        CountdownCategoryFactory(profile=profile, name="Bills")
        other = CountdownCategoryFactory(profile=profile, name="Birthdays")
        await db_session.commit()

        await login_as(user)

        response = await client.patch(
            f"/countdown-categories/{other.id}", json={"name": "Bills"}
        )

        assert response.status_code == 409

    async def test_read_missing_is_404(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()

        await login_as(user)

        response = await client.get("/countdown-categories/999999")

        assert response.status_code == 404

    async def test_read_another_users_category_is_403(
        self, client, db_session, login_as
    ):
        owner, intruder = UserFactory(), UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=owner)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        await login_as(intruder)

        response = await client.get(f"/countdown-categories/{category.id}")

        assert response.status_code == 403

    async def test_delete_category_clears_link_on_member_countdowns(
        self, client, db_session, login_as
    ):
        """Deleting a category clears category_id (FK SET NULL) on its members."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()
        category_id = category.id

        countdown = CountdownFactory(profile=profile, category_id=category_id)
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.delete(f"/countdown-categories/{category_id}")
        assert response.status_code == 200

        # Capture ids before expire_all() below - expire_all() expires the
        # ORM objects, and reading an expired attribute outside an await
        # raises MissingGreenlet on an AsyncSession.
        db_session.expire_all()
        row = await db_session.get(Countdown, countdown_id)
        assert row.category_id is None
        assert await db_session.get(CountdownCategory, category_id) is None

    async def test_delete_all_clears_link_across_profile(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        category = CountdownCategoryFactory(profile=profile, name="Bills")
        await db_session.commit()

        countdown = CountdownFactory(profile=profile, category_id=category.id)
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.delete(
            "/countdown-categories/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 1

        # Capture ids before expire_all() below - expire_all() expires the
        # ORM objects, and reading an expired attribute outside an await
        # raises MissingGreenlet on an AsyncSession.
        db_session.expire_all()
        row = await db_session.get(Countdown, countdown_id)
        assert row.category_id is None

    async def test_delete_all_unauthorized_leaves_target_profile_untouched(
        self, client, db_session, login_as
    ):
        """A non-owner must be rejected with 403 before the link-clearing
        UPDATE runs. This is the ordering the router has to get right: the
        pre-clear UPDATE happens before bulk_delete_in_profile's own
        ownership check, so it has to be preceded by an explicit
        get_owned_profile call."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        category = CountdownCategoryFactory(profile=foreign, name="Bills")
        await db_session.commit()
        category_id = category.id

        countdown = CountdownFactory(profile=foreign, category_id=category_id)
        await db_session.commit()
        countdown_id = countdown.id

        await login_as(user)

        response = await client.delete(
            "/countdown-categories/", params={"profile_id": foreign.id}
        )
        assert response.status_code == 403

        # Capture ids before expire_all() below - expire_all() expires the
        # ORM objects, and reading an expired attribute outside an await
        # raises MissingGreenlet on an AsyncSession.
        db_session.expire_all()
        row = await db_session.get(Countdown, countdown_id)
        assert row.category_id == category_id
        assert await db_session.get(CountdownCategory, category_id) is not None
