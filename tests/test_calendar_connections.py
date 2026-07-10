"""Tests for calendar connection endpoints (read-only ICS subscriptions)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from habit_tracker.main import app
from habit_tracker.schemas.db_models import CalendarConnection
from habit_tracker.services.calendar_events import get_ics_fetcher
from tests.factories import (
    CalendarConnectionFactory,
    ProfileFactory,
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


# A fixed, deterministic day: 2026-07-09 is a Thursday
TARGET_DATE = date(2026, 7, 9)

# Canned feed containing, relative to TARGET_DATE:
# - a timed event that day (14:00-15:00 New York)
# - an all-day event that day
# - a weekly Thursday RRULE event whose expansion lands that day (09:00)
# - a timed event the NEXT day (must not appear)
CANNED_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:timed-1
DTSTART;TZID=America/New_York:20260709T140000
DTEND;TZID=America/New_York:20260709T150000
SUMMARY:Timed meeting
LOCATION:Room 4
END:VEVENT
BEGIN:VEVENT
UID:allday-1
DTSTART;VALUE=DATE:20260709
DTEND;VALUE=DATE:20260710
SUMMARY:All day thing
END:VEVENT
BEGIN:VEVENT
UID:weekly-1
DTSTART;TZID=America/New_York:20260702T090000
DTEND;TZID=America/New_York:20260702T093000
RRULE:FREQ=WEEKLY;BYDAY=TH
SUMMARY:Weekly standup
END:VEVENT
BEGIN:VEVENT
UID:other-day
DTSTART;TZID=America/New_York:20260710T100000
DTEND;TZID=America/New_York:20260710T110000
SUMMARY:Tomorrow only
END:VEVENT
END:VCALENDAR
"""


class FakeFetcher:
    """Canned ICS fetcher that counts calls (dependency override target)."""

    def __init__(self, status_code=200, body=CANNED_ICS, etag='"v1"', exc=None):
        self.status_code = status_code
        self.body = body
        self.etag = etag
        self.exc = exc
        self.calls = 0
        self.urls: list[str] = []

    async def __call__(self, url, etag):
        self.calls += 1
        self.urls.append(url)
        if self.exc is not None:
            raise self.exc
        if self.status_code == 304:
            return 304, None, etag
        return self.status_code, self.body, self.etag


def override_fetcher(fetcher):
    """Route the events endpoint's ICS fetches to the given fake.

    The client fixture clears app.dependency_overrides at teardown, so this
    never leaks into other tests.
    """
    app.dependency_overrides[get_ics_fetcher] = lambda: fetcher


class TestListCalendarConnections:
    """Tests for GET /calendar-connections/ endpoint."""

    async def test_list_requires_profile_id(self, client, db_session, setup_factories):
        """profile_id query parameter is required (422 if missing)."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.get("/calendar-connections/")
        assert response.status_code == 422

    async def test_list_unknown_profile(self, client, db_session, setup_factories):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/", params={"profile_id": 99999}
        )
        assert response.status_code == 404

    async def test_list_foreign_profile(self, client, db_session, setup_factories):
        """Cannot list connections of another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/", params={"profile_id": foreign.id}
        )
        assert response.status_code == 403

    async def test_list_scoped_to_profile(self, client, db_session, setup_factories):
        """Only connections of the requested profile are returned."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="One")
        other_profile = ProfileFactory(user=user, name="Two")
        await db_session.commit()

        conn1 = CalendarConnectionFactory(profile=profile)
        conn2 = CalendarConnectionFactory(profile=profile)
        CalendarConnectionFactory(profile=other_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        ids = {c["id"] for c in data["calendar_connections"]}
        assert ids == {conn1.id, conn2.id}

    async def test_list_does_not_expose_cache_internals(
        self, client, db_session, setup_factories
    ):
        """cached_ics and etag are internal and never serialized."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(
            profile=profile, cached_ics=CANNED_ICS, etag='"v1"'
        )
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        connection = response.json()["calendar_connections"][0]
        assert "cached_ics" not in connection
        assert "etag" not in connection


class TestCreateCalendarConnection:
    """Tests for POST /calendar-connections/ endpoint."""

    async def test_create_connection_basic(self, client, db_session, setup_factories):
        """Create a connection and get its fields echoed back."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": profile.id,
                "name": "Work",
                "color": "#AA00BB",
                "url": "https://calendar.example.com/work.ics",
                "provider": "Google",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["profile_id"] == profile.id
        assert data["name"] == "Work"
        assert data["color"] == "#AA00BB"
        assert data["url"] == "https://calendar.example.com/work.ics"
        assert data["provider"] == "Google"
        assert data["enabled"] is True
        assert data["last_fetched_at"] is None
        assert data["last_error"] is None

    async def test_create_connection_webcal_url_normalized(
        self, client, db_session, setup_factories
    ):
        """webcal:// subscription links (Proton/Apple style) are rewritten to https://."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": profile.id,
                "name": "Proton",
                "color": "#6F9FE0",
                "url": (
                    "webcal://calendar.proton.me/api/calendar/v1/url/abc/"
                    "calendar.ics?CacheKey=k&PassphraseKey=p"
                ),
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["url"] == (
            "https://calendar.proton.me/api/calendar/v1/url/abc/"
            "calendar.ics?CacheKey=k&PassphraseKey=p"
        )

    async def test_patch_connection_webcal_url_normalized(
        self, client, db_session, setup_factories
    ):
        """PATCHing a webcal:// url stores the https:// form."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        connection = CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}",
            json={"url": "webcal://example.com/feed.ics"},
        )
        assert response.status_code == 200
        assert response.json()["url"] == "https://example.com/feed.ics"

    async def test_create_connection_foreign_profile(
        self, client, db_session, setup_factories
    ):
        """Cannot create a connection in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": foreign.id,
                "name": "Nope",
                "color": "#123456",
                "url": "https://calendar.example.com/nope.ics",
            },
        )
        assert response.status_code == 403

    async def test_create_connection_unknown_profile(
        self, client, db_session, setup_factories
    ):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": 99999,
                "name": "Nope",
                "color": "#123456",
                "url": "https://calendar.example.com/nope.ics",
            },
        )
        assert response.status_code == 404

    async def test_create_connection_invalid_url(
        self, client, db_session, setup_factories
    ):
        """A URL that is not http(s)/webcal is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": profile.id,
                "name": "Bad",
                "color": "#123456",
                "url": "ftp://calendar.example.com/feed.ics",
            },
        )
        assert response.status_code == 422

    async def test_create_connection_invalid_color(
        self, client, db_session, setup_factories
    ):
        """Invalid color is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        await login_as(client, user)

        response = await client.post(
            "/calendar-connections/",
            json={
                "profile_id": profile.id,
                "name": "Bad",
                "color": "blue",
                "url": "https://calendar.example.com/feed.ics",
            },
        )
        assert response.status_code == 422


class TestGetCalendarConnection:
    """Tests for GET /calendar-connections/{connection_id} endpoint."""

    async def test_get_connection(self, client, db_session, setup_factories):
        """Retrieve a connection by its ID."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile, name="Work")
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(f"/calendar-connections/{connection.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == connection.id
        assert data["name"] == "Work"

    async def test_get_nonexistent_connection(
        self, client, db_session, setup_factories
    ):
        """Return 404 for non-existent connection."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.get("/calendar-connections/99999")
        assert response.status_code == 404

    async def test_get_other_user_connection(
        self, client, db_session, setup_factories
    ):
        """User cannot access a connection in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.get(f"/calendar-connections/{connection.id}")
        assert response.status_code == 403


class TestPatchCalendarConnection:
    """Tests for PATCH /calendar-connections/{connection_id} endpoint."""

    async def test_patch_connection_rename(self, client, db_session, setup_factories):
        """Rename a connection; updated_date is stamped."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile, name="Old Name")
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}", json={"name": "New Name"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["updated_date"] is not None

    async def test_patch_connection_disable(self, client, db_session, setup_factories):
        """Disable a connection."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile, enabled=True)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}", json={"enabled": False}
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    async def test_patch_url_change_clears_cache(
        self, client, db_session, setup_factories
    ):
        """Changing the URL clears cached_ics/etag/last_fetched_at/last_error."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(
            profile=profile,
            cached_ics=CANNED_ICS,
            etag='"v1"',
            last_fetched_at=datetime.now(),
            last_error="HTTP 500",
        )
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}",
            json={"url": "https://calendar.example.com/other.ics"},
        )
        assert response.status_code == 200

        await db_session.refresh(connection)
        assert connection.url == "https://calendar.example.com/other.ics"
        assert connection.cached_ics is None
        assert connection.etag is None
        assert connection.last_fetched_at is None
        assert connection.last_error is None

    async def test_patch_same_url_keeps_cache(
        self, client, db_session, setup_factories
    ):
        """Re-sending the same URL does not throw the cache away."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(
            profile=profile,
            url="https://calendar.example.com/same.ics",
            cached_ics=CANNED_ICS,
            etag='"v1"',
            last_fetched_at=datetime.now(),
        )
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}",
            json={"url": "https://calendar.example.com/same.ics", "name": "Renamed"},
        )
        assert response.status_code == 200

        await db_session.refresh(connection)
        assert connection.cached_ics == CANNED_ICS
        assert connection.etag == '"v1"'

    async def test_patch_connection_null_name(
        self, client, db_session, setup_factories
    ):
        """An explicit null for the non-nullable name is rejected (422)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}", json={"name": None}
        )
        assert response.status_code == 422

    async def test_patch_other_user_connection(
        self, client, db_session, setup_factories
    ):
        """User cannot patch a connection in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.patch(
            f"/calendar-connections/{connection.id}", json={"name": "Hijacked"}
        )
        assert response.status_code == 403


class TestDeleteCalendarConnection:
    """Tests for DELETE /calendar-connections/{connection_id} endpoint."""

    async def test_delete_connection(self, client, db_session, setup_factories):
        """Delete a connection by its ID."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.delete(f"/calendar-connections/{connection.id}")
        assert response.status_code == 200

        result = await db_session.execute(
            select(CalendarConnection).filter(
                CalendarConnection.id == connection.id
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_other_user_connection(
        self, client, db_session, setup_factories
    ):
        """User cannot delete a connection in another user's profile (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign_profile = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=foreign_profile)
        await db_session.commit()

        await login_as(client, user)

        response = await client.delete(f"/calendar-connections/{connection.id}")
        assert response.status_code == 403

    async def test_delete_nonexistent_connection(
        self, client, db_session, setup_factories
    ):
        """Return 404 for non-existent connection."""
        user = UserFactory()
        await db_session.commit()

        await login_as(client, user)

        response = await client.delete("/calendar-connections/99999")
        assert response.status_code == 404


class TestCalendarEvents:
    """Tests for GET /calendar-connections/events endpoint."""

    async def test_events_normalized_and_ordered(
        self, client, db_session, setup_factories
    ):
        """Events are normalized, recurrence-expanded, all-day first, then by
        start; events on other days are excluded."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(
            profile=profile, name="Work", color="#112233"
        )
        await db_session.commit()

        fetcher = FakeFetcher()
        override_fetcher(fetcher)

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == TARGET_DATE.isoformat()
        assert data["errors"] == []

        titles = [e["title"] for e in data["events"]]
        # all-day first, then timed events ordered by start time
        assert titles == ["All day thing", "Weekly standup", "Timed meeting"]
        assert "Tomorrow only" not in titles

        all_day = data["events"][0]
        assert all_day["all_day"] is True
        assert all_day["start"] == "2026-07-09T00:00:00"
        assert all_day["connection_id"] == connection.id
        assert all_day["calendar_name"] == "Work"
        assert all_day["color"] == "#112233"

        timed = data["events"][2]
        assert timed["all_day"] is False
        assert timed["start"] == "2026-07-09T14:00:00-04:00"  # feed tz preserved
        assert timed["end"] == "2026-07-09T15:00:00-04:00"
        assert timed["location"] == "Room 4"

    async def test_events_default_date_is_today(
        self, client, db_session, setup_factories
    ):
        """Without target_date the endpoint returns today's events."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        today = date.today()
        ics_today = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//Test//EN\n"
            "BEGIN:VEVENT\nUID:today-1\n"
            f"DTSTART;VALUE=DATE:{today.strftime('%Y%m%d')}\n"
            f"DTEND;VALUE=DATE:{(today + timedelta(days=1)).strftime('%Y%m%d')}\n"
            "SUMMARY:Today marker\nEND:VEVENT\nEND:VCALENDAR\n"
        )
        override_fetcher(FakeFetcher(body=ics_today))

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == today.isoformat()
        assert [e["title"] for e in data["events"]] == ["Today marker"]

    async def test_events_unknown_profile(self, client, db_session, setup_factories):
        """Return 404 for a non-existent profile."""
        user = UserFactory()
        await db_session.commit()

        override_fetcher(FakeFetcher())
        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events", params={"profile_id": 99999}
        )
        assert response.status_code == 404

    async def test_events_foreign_profile(self, client, db_session, setup_factories):
        """Cannot read another user's calendar events (403)."""
        user = UserFactory()
        other_user = UserFactory()
        await db_session.commit()

        foreign = ProfileFactory(user=other_user, name="Theirs")
        await db_session.commit()

        override_fetcher(FakeFetcher())
        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events", params={"profile_id": foreign.id}
        )
        assert response.status_code == 403

    async def test_events_skips_disabled_connections(
        self, client, db_session, setup_factories
    ):
        """Disabled connections are neither fetched nor included."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        enabled = CalendarConnectionFactory(profile=profile, enabled=True)
        CalendarConnectionFactory(profile=profile, enabled=False)
        await db_session.commit()

        fetcher = FakeFetcher()
        override_fetcher(fetcher)

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert fetcher.calls == 1  # only the enabled connection was fetched
        assert fetcher.urls == [enabled.url]
        assert {e["connection_id"] for e in data["events"]} == {enabled.id}

    async def test_events_cache_hit_within_ttl(
        self, client, db_session, setup_factories
    ):
        """Two events calls within the TTL fetch the feed exactly once."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        connection = CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        fetcher = FakeFetcher()
        override_fetcher(fetcher)

        await login_as(client, user)

        params = {"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()}
        first = await client.get("/calendar-connections/events", params=params)
        assert first.status_code == 200
        assert len(first.json()["events"]) == 3

        second = await client.get("/calendar-connections/events", params=params)
        assert second.status_code == 200
        assert len(second.json()["events"]) == 3

        assert fetcher.calls == 1  # second call served from cache

        await db_session.refresh(connection)
        assert connection.cached_ics == CANNED_ICS
        assert connection.etag == '"v1"'
        assert connection.last_fetched_at is not None
        assert connection.last_error is None

    async def test_events_fetch_exception_serves_stale_cache(
        self, client, db_session, setup_factories
    ):
        """A raising fetcher keeps the stale cache serving events, reports the
        failure in errors, persists last_error and records the attempt time
        (failure backoff)."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            name="Work",
            cached_ics=CANNED_ICS,
            last_fetched_at=stale,
        )
        await db_session.commit()

        override_fetcher(FakeFetcher(exc=RuntimeError("connection refused")))

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        # stale cache still parsed
        assert len(data["events"]) == 3
        # failure surfaced per connection
        assert len(data["errors"]) == 1
        assert data["errors"][0].startswith("Work:")

        await db_session.refresh(connection)
        assert connection.last_error is not None
        assert connection.cached_ics == CANNED_ICS  # stale cache kept
        assert connection.last_fetched_at > stale  # attempt time recorded

    async def test_events_failure_backoff(
        self, client, db_session, setup_factories
    ):
        """A failed feed is not re-attempted within the 5-minute error TTL
        (stale cache still served), but IS re-attempted once the backoff has
        elapsed."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            name="Work",
            cached_ics=CANNED_ICS,
            last_fetched_at=stale,
        )
        await db_session.commit()

        fetcher = FakeFetcher(exc=RuntimeError("connection refused"))
        override_fetcher(fetcher)

        await login_as(client, user)

        params = {"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()}

        first = await client.get("/calendar-connections/events", params=params)
        assert first.status_code == 200
        assert len(first.json()["events"]) == 3  # stale cache served
        assert fetcher.calls == 1

        # Second call within the 5-minute error TTL: NOT re-attempted, stale
        # cache still served
        second = await client.get("/calendar-connections/events", params=params)
        assert second.status_code == 200
        assert len(second.json()["events"]) == 3
        assert fetcher.calls == 1  # backoff prevented a re-fetch

        # Backdate the failed attempt beyond the error TTL: re-attempted
        await db_session.refresh(connection)
        assert connection.last_error is not None
        connection.last_fetched_at = datetime.now() - timedelta(minutes=6)
        await db_session.commit()

        third = await client.get("/calendar-connections/events", params=params)
        assert third.status_code == 200
        assert len(third.json()["events"]) == 3
        assert fetcher.calls == 2  # error TTL elapsed -> re-fetched

    async def test_events_http_error_serves_stale_cache(
        self, client, db_session, setup_factories
    ):
        """A non-2xx response keeps the stale cache and reports 'Name: HTTP n'."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            name="Work",
            cached_ics=CANNED_ICS,
            last_fetched_at=stale,
        )
        await db_session.commit()

        override_fetcher(FakeFetcher(status_code=404, body="not found"))

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) == 3
        assert data["errors"] == ["Work: HTTP 404"]

        await db_session.refresh(connection)
        assert connection.last_error == "HTTP 404"
        assert connection.cached_ics == CANNED_ICS
        assert connection.last_fetched_at > stale  # attempt time recorded

    async def test_events_unparseable_200_keeps_good_cache(
        self, client, db_session, setup_factories
    ):
        """A 200 response with a non-ICS body (e.g. an HTML maintenance page)
        must not clobber a good cache: events keep coming from the stale
        cache and the failure is recorded like any other fetch failure."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            name="Work",
            cached_ics=CANNED_ICS,
            last_fetched_at=stale,
        )
        await db_session.commit()

        override_fetcher(
            FakeFetcher(body="<html><body>Down for maintenance</body></html>")
        )

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        # events still served from the good stale cache
        assert len(data["events"]) == 3
        assert data["errors"] == ["Work: feed returned unparseable content"]

        await db_session.refresh(connection)
        assert connection.cached_ics == CANNED_ICS  # good cache NOT clobbered
        assert connection.last_error == "feed returned unparseable content"
        assert connection.last_fetched_at > stale  # attempt time recorded

    async def test_events_oversized_feed_keeps_stale_cache(
        self, client, db_session, setup_factories
    ):
        """A feed body over 5 MB is treated as a fetch failure: stale cache
        kept and served, 'feed too large' recorded."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            name="Work",
            cached_ics=CANNED_ICS,
            last_fetched_at=stale,
        )
        await db_session.commit()

        oversized = "X" * (5 * 1024 * 1024 + 1)
        override_fetcher(FakeFetcher(body=oversized))

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) == 3  # stale cache still served
        assert data["errors"] == ["Work: feed too large"]

        await db_session.refresh(connection)
        assert connection.cached_ics == CANNED_ICS
        assert connection.last_error == "feed too large"

    async def test_events_304_keeps_cache_and_bumps_timestamp(
        self, client, db_session, setup_factories
    ):
        """304 Not Modified keeps the cached body and bumps last_fetched_at."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        stale = datetime.now() - timedelta(hours=2)
        connection = CalendarConnectionFactory(
            profile=profile,
            cached_ics=CANNED_ICS,
            etag='"v1"',
            last_fetched_at=stale,
        )
        await db_session.commit()

        fetcher = FakeFetcher(status_code=304)
        override_fetcher(fetcher)

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []
        assert len(data["events"]) == 3  # parsed from the kept cache

        assert fetcher.calls == 1

        await db_session.refresh(connection)
        assert connection.cached_ics == CANNED_ICS  # cache kept
        assert connection.etag == '"v1"'
        assert connection.last_fetched_at > stale  # bumped
        assert connection.last_error is None

    async def test_events_malformed_feed_reports_error(
        self, client, db_session, setup_factories
    ):
        """A malformed feed becomes a connection-level error, not a 500."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(profile=profile, name="Broken")
        await db_session.commit()

        override_fetcher(FakeFetcher(body="this is not an ICS feed"))

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["events"] == []
        assert len(data["errors"]) == 1
        assert data["errors"][0].startswith("Broken:")

    async def test_events_tz_day_boundaries(
        self, client, db_session, setup_factories
    ):
        """A UTC-encoded evening event (2026-07-10T01:00Z == 2026-07-09 21:00
        in New York) belongs to 2026-07-09 when tz=America/New_York, but not
        when tz is omitted or UTC."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        utc_evening_ics = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//Test//EN\n"
            "BEGIN:VEVENT\nUID:utc-evening\n"
            "DTSTART:20260710T010000Z\nDTEND:20260710T020000Z\n"
            "SUMMARY:Late night sync\nEND:VEVENT\nEND:VCALENDAR\n"
        )
        override_fetcher(FakeFetcher(body=utc_evening_ics))

        await login_as(client, user)

        base = {"profile_id": profile.id, "target_date": TARGET_DATE.isoformat()}

        # Viewed from New York, the event is on the evening of the 9th
        response = await client.get(
            "/calendar-connections/events",
            params={**base, "tz": "America/New_York"},
        )
        assert response.status_code == 200
        assert [e["title"] for e in response.json()["events"]] == ["Late night sync"]

        # Without tz the feed's own timezone (UTC) decides: it's on the 10th
        response = await client.get("/calendar-connections/events", params=base)
        assert response.status_code == 200
        assert response.json()["events"] == []

        # Explicit UTC agrees with the feed: not on the 9th
        response = await client.get(
            "/calendar-connections/events", params={**base, "tz": "UTC"}
        )
        assert response.status_code == 200
        assert response.json()["events"] == []

    async def test_events_tz_all_day_events_match_date(
        self, client, db_session, setup_factories
    ):
        """All-day events still land on the right date when tz is passed."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        override_fetcher(FakeFetcher())

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={
                "profile_id": profile.id,
                "target_date": TARGET_DATE.isoformat(),
                "tz": "America/New_York",
            },
        )
        assert response.status_code == 200
        data = response.json()
        titles = [e["title"] for e in data["events"]]
        assert "All day thing" in titles  # DATE-valued event matches the day
        assert "Tomorrow only" not in titles
        all_day = data["events"][0]
        assert all_day["title"] == "All day thing"
        assert all_day["all_day"] is True

    async def test_events_invalid_tz_rejected(
        self, client, db_session, setup_factories
    ):
        """An invalid IANA timezone name is rejected with 422."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        override_fetcher(FakeFetcher())
        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "tz": "Not/A_Zone"},
        )
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    async def test_events_default_date_uses_tz_today(
        self, client, db_session, setup_factories
    ):
        """Without target_date, 'today' is computed in the requested zone,
        not server-local time."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        CalendarConnectionFactory(profile=profile)
        await db_session.commit()

        override_fetcher(FakeFetcher())
        await login_as(client, user)

        # UTC+14: the zone most likely to differ from server-local today
        zone_name = "Pacific/Kiritimati"
        before = datetime.now(ZoneInfo(zone_name)).date()
        response = await client.get(
            "/calendar-connections/events",
            params={"profile_id": profile.id, "tz": zone_name},
        )
        after = datetime.now(ZoneInfo(zone_name)).date()

        assert response.status_code == 200
        # Tolerate a midnight rollover between the two datetime.now() calls
        assert response.json()["date"] in {before.isoformat(), after.isoformat()}

    async def test_events_no_connections(self, client, db_session, setup_factories):
        """A profile without connections gets an empty, error-free response."""
        user = UserFactory()
        await db_session.commit()

        profile = ProfileFactory(user=user, name="Personal")
        await db_session.commit()

        fetcher = FakeFetcher()
        override_fetcher(fetcher)

        await login_as(client, user)

        response = await client.get(
            "/calendar-connections/events", params={"profile_id": profile.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["events"] == []
        assert data["errors"] == []
        assert fetcher.calls == 0
