"""Daily journal entity, router, and the upsert-by-date contract.

Covers the JournalEntry table, the JournalEntryCreate/Read/List models
(including their own rejection tests for bad input), and the /journal router
end to end.
"""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from habit_tracker.models import (
    JournalEntryCreate,
    JournalEntryList,
)
from habit_tracker.routers import journal as journal_router
from habit_tracker.schemas.db_models import JournalEntry
from tests.factories import JournalEntryFactory, ProfileFactory, UserFactory


class TestJournalEntryTable:
    async def test_stores_an_entry_for_a_day(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        db_session.add(
            JournalEntry(
                profile_id=profile.id,
                entry_date=date(2026, 9, 10),
                body="Shipped the journal table.",
                day_quality="productive",
            )
        )
        await db_session.commit()

        row = (
            await db_session.execute(
                select(JournalEntry).filter(JournalEntry.profile_id == profile.id)
            )
        ).scalar_one()
        assert row.entry_date == date(2026, 9, 10)
        assert row.day_quality == "productive"

    async def test_one_entry_per_profile_per_day(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()

        db_session.add(
            JournalEntry(profile_id=profile.id, entry_date=date(2026, 9, 10))
        )
        await db_session.commit()

        db_session.add(
            JournalEntry(profile_id=profile.id, entry_date=date(2026, 9, 10))
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_the_same_day_in_two_profiles_is_allowed(self, db_session):
        user = UserFactory()
        await db_session.commit()

        one = ProfileFactory(user=user)
        two = ProfileFactory(user=user)
        await db_session.commit()

        db_session.add(JournalEntry(profile_id=one.id, entry_date=date(2026, 9, 10)))
        db_session.add(JournalEntry(profile_id=two.id, entry_date=date(2026, 9, 10)))
        await db_session.commit()

        rows = (await db_session.execute(select(JournalEntry))).scalars().all()
        assert len(rows) == 2


class TestProfileJournalSettings:
    async def test_journal_is_off_by_default(self, db_session):
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user)
        await db_session.commit()
        await db_session.refresh(profile)

        assert profile.journal_enabled is False
        assert profile.journal_prompt_time is None
        # True, unlike journal_enabled: once the journal is on, both prompts
        # are the format.
        assert profile.journal_gratitude_enabled is True
        assert profile.journal_prompt is None


class TestJournalEntryModels:
    def test_body_and_quality_are_optional(self):
        model = JournalEntryCreate(profile_id=1)
        assert model.body is None
        assert model.day_quality is None

    def test_valid_quality_accepted(self):
        model = JournalEntryCreate(profile_id=1, day_quality="great")
        assert model.day_quality == "great"

    @pytest.mark.parametrize("bad", ["amazing", "GOOD", "", "3", "okay"])
    def test_quality_outside_the_vocabulary_rejected(self, bad):
        """Case matters and near-misses are rejected: a typo must not
        silently become a quality nothing can group by."""
        with pytest.raises(ValueError, match="must be one of"):
            JournalEntryCreate(profile_id=1, day_quality=bad)

    def test_whitespace_only_body_becomes_none(self):
        model = JournalEntryCreate(profile_id=1, body="   \n  ")
        assert model.body is None

    def test_list_envelope_defaults_to_empty(self):
        envelope = JournalEntryList(total=0, limit=100, offset=0)
        assert envelope.entries == []


class TestJournalRouter:
    async def _profile(self, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()
        await login_as(user)
        return profile

    async def test_put_creates_and_returns_201(self, client, db_session, login_as):
        profile = await self._profile(db_session, login_as)

        response = await client.put(
            "/journal/2026-09-10",
            json={
                "profile_id": profile.id,
                "body": "A good day.",
                "day_quality": "productive",
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_date"] == "2026-09-10"
        assert response.json()["day_quality"] == "productive"

    async def test_put_twice_updates_and_returns_200(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)
        payload = {"profile_id": profile.id, "day_quality": "tiring"}

        first = await client.put("/journal/2026-09-10", json=payload)
        second = await client.put(
            "/journal/2026-09-10", json={**payload, "day_quality": "great"}
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["day_quality"] == "great"

    async def test_put_resolves_a_commit_race_to_200_not_500(
        self, client, db_session, login_as, monkeypatch
    ):
        """A concurrent request may insert this day between our fetch and our
        commit, hitting the unique constraint. The handler must recover by
        re-fetching and updating the winning row - not crash trying to reuse
        the now-expired `profile` instance after the rollback (fix 1)."""
        profile = await self._profile(db_session, login_as)
        entry_date = date(2026, 9, 10)

        # The "concurrent" row that will already be in place when our insert
        # hits the unique constraint on (profile_id, entry_date).
        db_session.add(
            JournalEntry(
                profile_id=profile.id, entry_date=entry_date, day_quality="rough"
            )
        )
        await db_session.commit()

        real_fetch = journal_router._fetch
        calls = {"n": 0}

        async def fetch_missing_on_first_call(db, profile_id, checked_date):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_fetch(db, profile_id, checked_date)

        monkeypatch.setattr(journal_router, "_fetch", fetch_missing_on_first_call)

        response = await client.put(
            f"/journal/{entry_date.isoformat()}",
            json={
                "profile_id": profile.id,
                "body": "Wins the race",
                "day_quality": "great",
            },
        )

        assert response.status_code == 200
        assert response.json()["body"] == "Wins the race"
        assert response.json()["day_quality"] == "great"

    async def test_put_ignores_entry_date_in_the_body(
        self, client, db_session, login_as
    ):
        """The path is the authority; a mismatched body date must not win."""
        profile = await self._profile(db_session, login_as)

        response = await client.put(
            "/journal/2026-09-10",
            json={
                "profile_id": profile.id,
                "entry_date": "1999-01-01",
                "day_quality": "good",
            },
        )

        assert response.json()["entry_date"] == "2026-09-10"

    async def test_get_returns_404_for_a_day_with_no_entry(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)

        response = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert response.status_code == 404

    async def test_list_is_newest_first(self, client, db_session, login_as):
        profile = await self._profile(db_session, login_as)
        for day in ("2026-09-08", "2026-09-10", "2026-09-09"):
            await client.put(
                f"/journal/{day}",
                json={"profile_id": profile.id, "day_quality": "good"},
            )

        response = await client.get(f"/journal/?profile_id={profile.id}")

        dates = [e["entry_date"] for e in response.json()["entries"]]
        assert dates == ["2026-09-10", "2026-09-09", "2026-09-08"]
        assert response.json()["total"] == 3

    async def test_list_total_counts_beyond_a_truncated_page(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)
        for day in ("2026-09-08", "2026-09-10", "2026-09-09"):
            await client.put(
                f"/journal/{day}",
                json={"profile_id": profile.id, "day_quality": "good"},
            )

        response = await client.get(f"/journal/?profile_id={profile.id}&limit=1")

        assert response.json()["total"] == 3
        assert len(response.json()["entries"]) == 1

    async def test_list_filters_by_date_range(self, client, db_session, login_as):
        profile = await self._profile(db_session, login_as)
        for day in ("2026-09-08", "2026-09-09", "2026-09-10"):
            await client.put(
                f"/journal/{day}",
                json={"profile_id": profile.id, "day_quality": "good"},
            )

        response = await client.get(
            f"/journal/?profile_id={profile.id}&from_date=2026-09-09&to_date=2026-09-09"
        )

        dates = [e["entry_date"] for e in response.json()["entries"]]
        assert dates == ["2026-09-09"]

    async def test_delete_removes_the_day(self, client, db_session, login_as):
        profile = await self._profile(db_session, login_as)
        await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "day_quality": "good"},
        )

        deleted = await client.delete(f"/journal/2026-09-10?profile_id={profile.id}")
        after = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert deleted.status_code == 204
        assert after.status_code == 404

    async def test_delete_returns_404_for_a_day_with_no_entry(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)

        response = await client.delete(f"/journal/1999-01-01?profile_id={profile.id}")

        assert response.status_code == 404

    async def test_put_round_trips_gratitude(self, client, db_session, login_as):
        profile = await self._profile(db_session, login_as)

        await client.put(
            "/journal/2026-09-10",
            json={
                "profile_id": profile.id,
                "body": "Shipped the journal.",
                "gratitude": "sydney for making dinner",
            },
        )
        response = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert response.json()["gratitude"] == "sydney for making dinner"
        assert response.json()["body"] == "Shipped the journal."

    async def test_put_stores_whitespace_only_gratitude_as_null(
        self, client, db_session, login_as
    ):
        """Same trimming as body, so "has a gratitude" stays a null check."""
        profile = await self._profile(db_session, login_as)

        await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "gratitude": "   \n  "},
        )
        response = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert response.json()["gratitude"] is None

    async def test_put_clears_gratitude_when_omitted(
        self, client, db_session, login_as
    ):
        """PUT replaces the whole day, so an omitted field is a cleared field."""
        profile = await self._profile(db_session, login_as)
        await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "gratitude": "the sun"},
        )

        await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "body": "Only prose today."},
        )
        response = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert response.json()["gratitude"] is None

    async def test_put_rejects_an_unknown_day_quality_with_422(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)

        response = await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "day_quality": "amazing"},
        )

        assert response.status_code == 422

    async def test_put_stores_whitespace_only_body_as_null(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)

        await client.put(
            "/journal/2026-09-10",
            json={"profile_id": profile.id, "body": "   \n  "},
        )
        after = await client.get(f"/journal/2026-09-10?profile_id={profile.id}")

        assert after.json()["body"] is None

    async def test_list_pages_across_a_boundary_with_no_duplicate_or_drop(
        self, client, db_session, login_as
    ):
        profile = await self._profile(db_session, login_as)
        for n in range(5):
            await client.put(
                f"/journal/2026-09-{n + 1:02d}",
                json={"profile_id": profile.id, "day_quality": "good"},
            )

        first = await client.get(f"/journal/?profile_id={profile.id}&limit=2&offset=0")
        second = await client.get(f"/journal/?profile_id={profile.id}&limit=2&offset=2")
        third = await client.get(f"/journal/?profile_id={profile.id}&limit=2&offset=4")

        ids = [
            e["id"] for page in (first, second, third) for e in page.json()["entries"]
        ]
        assert len(ids) == 5
        assert len(set(ids)) == 5


class TestDeleteAllJournalEntries:
    async def test_deletes_every_entry_in_the_profile(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        profile = ProfileFactory(user=user)
        await db_session.commit()
        await login_as(user)

        for day in ("2026-09-09", "2026-09-10"):
            await client.put(
                f"/journal/{day}",
                json={"profile_id": profile.id, "day_quality": "good"},
            )

        response = await client.delete(f"/journal/?profile_id={profile.id}")
        remaining = await client.get(f"/journal/?profile_id={profile.id}")

        assert response.status_code == 200
        assert response.json()["detail"] == "Deleted 2 journal entries"
        assert remaining.json()["total"] == 0


class TestJournalAuthorization:
    """Cross-profile access to another user's journal is forbidden (403)."""

    async def _foreign_profile(self, db_session, login_as):
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(user)
        return foreign

    async def test_list_foreign_profile(self, client, db_session, login_as):
        foreign = await self._foreign_profile(db_session, login_as)

        response = await client.get(f"/journal/?profile_id={foreign.id}")

        assert response.status_code == 403

    async def test_get_entry_foreign_profile(self, client, db_session, login_as):
        foreign = await self._foreign_profile(db_session, login_as)
        JournalEntryFactory(profile=foreign, entry_date=date(2026, 9, 10))
        await db_session.commit()

        response = await client.get(f"/journal/2026-09-10?profile_id={foreign.id}")

        assert response.status_code == 403

    async def test_put_entry_foreign_profile(self, client, db_session, login_as):
        foreign = await self._foreign_profile(db_session, login_as)

        response = await client.put(
            "/journal/2026-09-10",
            json={"profile_id": foreign.id, "day_quality": "good"},
        )

        assert response.status_code == 403

    async def test_delete_entry_foreign_profile(self, client, db_session, login_as):
        foreign = await self._foreign_profile(db_session, login_as)
        JournalEntryFactory(profile=foreign, entry_date=date(2026, 9, 10))
        await db_session.commit()

        response = await client.delete(f"/journal/2026-09-10?profile_id={foreign.id}")

        assert response.status_code == 403
