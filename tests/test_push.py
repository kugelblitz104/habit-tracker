"""Push endpoints: VAPID key, subscription upsert/delete, and the test send."""

from types import SimpleNamespace

import pytest
from py_vapid import Vapid02, b64urlencode
from sqlalchemy import select

from habit_tracker.core import rate_limit
from habit_tracker.core.config import settings
from habit_tracker.schemas.db_models import PushSubscription
from habit_tracker.services import web_push
from habit_tracker.services.notifications import CONFIG
from tests.factories import ProfileFactory, UserFactory, push_keys

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


KEY_1, AUTH_1 = push_keys(1)
KEY_2, AUTH_2 = push_keys(2)


def _body(profile, **overrides):
    return {
        "profile_id": profile.id,
        "endpoint": ENDPOINT,
        "p256dh": KEY_1,
        "auth": AUTH_1,
        **overrides,
    }


async def _profile(db_session, owner):
    """A profile of `owner`, reduced to its id: the API commits on the shared
    session, which expires ORM instances."""
    profile = ProfileFactory(user=owner)
    await db_session.commit()
    await db_session.refresh(profile)
    return SimpleNamespace(id=profile.id)


async def _rows(db_session, profile):
    db_session.expire_all()
    result = await db_session.scalars(
        select(PushSubscription).where(PushSubscription.profile_id == profile.id)
    )
    return result.all()


@pytest.fixture
async def owner(client, db_session, login_as):
    user = UserFactory()
    await db_session.commit()
    await login_as(user)
    return user


@pytest.fixture
def sent(monkeypatch):
    """Replace the sender; each call is recorded and answers `sent.status`."""

    class Recorder(list):
        status = 201

    recorder = Recorder()

    async def fake_send(subscription, payload):
        recorder.append((subscription.endpoint, payload))
        return recorder.status

    monkeypatch.setattr(settings, "vapid_private_key", "configured")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@example.com")
    monkeypatch.setattr(web_push, "send", fake_send)
    return recorder


class TestVapidPublicKey:
    async def test_returns_the_derived_key(self, client, monkeypatch):
        vapid = Vapid02()
        vapid.generate_keys()
        raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        monkeypatch.setattr(settings, "vapid_private_key", b64urlencode(raw))
        monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@example.com")

        response = await client.get("/push/vapid-public-key")

        assert response.status_code == 200
        assert response.json() == {"public_key": web_push.vapid_public_key()}

    @pytest.mark.parametrize(
        ("key", "subject"), [("", ""), ("configured", ""), ("", "mailto:a@b.c")]
    )
    async def test_404_unless_key_and_subject_are_both_set(
        self, client, monkeypatch, key, subject
    ):
        monkeypatch.setattr(settings, "vapid_private_key", key)
        monkeypatch.setattr(settings, "vapid_subject", subject)
        response = await client.get("/push/vapid-public-key")
        assert response.status_code == 404


class TestSubscribe:
    async def test_creates_a_subscription(self, client, db_session, owner):
        profile = await _profile(db_session, owner)

        response = await client.post("/push/subscriptions", json=_body(profile))

        assert response.status_code == 204
        [row] = await _rows(db_session, profile)
        assert (row.endpoint, row.p256dh, row.auth) == (ENDPOINT, KEY_1, AUTH_1)

    async def test_same_endpoint_refreshes_keys_in_place(
        self, client, db_session, owner
    ):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))

        response = await client.post(
            "/push/subscriptions", json=_body(profile, p256dh=KEY_2, auth=AUTH_2)
        )

        assert response.status_code == 204
        [row] = await _rows(db_session, profile)
        assert (row.p256dh, row.auth) == (KEY_2, AUTH_2)

    async def test_other_endpoint_adds_a_row(self, client, db_session, owner):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=ENDPOINT + "2")
        )
        assert len(await _rows(db_session, profile)) == 2

    async def test_one_browser_can_serve_two_profiles(self, client, db_session, owner):
        first = await _profile(db_session, owner)
        second = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(first))
        await client.post("/push/subscriptions", json=_body(second))
        assert len(await _rows(db_session, first)) == 1
        assert len(await _rows(db_session, second)) == 1

    async def test_a_full_profile_refuses_another_device_but_refreshes_its_own(
        self, client, db_session, owner
    ):
        profile = await _profile(db_session, owner)
        limit = CONFIG["push"]["max_subscriptions_per_profile"]
        for i in range(limit):
            response = await client.post(
                "/push/subscriptions", json=_body(profile, endpoint=f"{ENDPOINT}{i}")
            )
            assert response.status_code == 204

        extra = await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=f"{ENDPOINT}x")
        )
        refresh = await client.post(
            "/push/subscriptions",
            json=_body(profile, endpoint=f"{ENDPOINT}0", p256dh=KEY_2, auth=AUTH_2),
        )

        assert extra.status_code == 409
        assert refresh.status_code == 204
        assert len(await _rows(db_session, profile)) == limit

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://127.0.0.1/send",
            "https://[::1]/send",
            "https://localhost/send",
            "https://push.example.com/send",
            "https://evil.com/fcm.googleapis.com",
            "https://fcm.googleapis.com.evil.com/send",
            "https://user:pw@fcm.googleapis.com/send",
            "https://fcm.googleapis.com:8443/send",
            "https://notify.windows.com/send",
            "ftp://fcm.googleapis.com/send",
            "fcm.googleapis.com/send",
            "https://evil.example\\.push.apple.com/x",
            "https://x;.push.apple.com/x",
            "https://.push.apple.com/x",
            "https://fcm.googleapis.com/" + "a" * 2048,
        ],
    )
    async def test_bad_endpoints_are_rejected(
        self, client, db_session, owner, endpoint
    ):
        profile = await _profile(db_session, owner)
        response = await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=endpoint)
        )
        assert response.status_code == 422
        response = await client.request(
            "DELETE",
            "/push/subscriptions",
            json={"profile_id": profile.id, "endpoint": endpoint},
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://fcm.googleapis.com:443/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/abc",
            "https://abc.push.apple.com/abc",
            "https://db5p.notify.windows.com/?token=abc",
        ],
    )
    async def test_real_push_service_endpoints_are_accepted(
        self, client, db_session, owner, endpoint
    ):
        profile = await _profile(db_session, owner)
        response = await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=endpoint)
        )
        assert response.status_code == 204

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("p256dh", "key-1"),
            ("p256dh", b64urlencode(b"\x04" + bytes(63))),
            ("p256dh", b64urlencode(b"\x02" + bytes(64))),
            ("auth", "auth-1"),
            ("auth", b64urlencode(bytes(15))),
            ("auth", b64urlencode(bytes(17))),
        ],
    )
    async def test_bad_keys_are_rejected(self, client, db_session, owner, field, value):
        profile = await _profile(db_session, owner)
        response = await client.post(
            "/push/subscriptions", json=_body(profile, **{field: value})
        )
        assert response.status_code == 422

    async def test_padded_keys_are_accepted(self, client, db_session, owner):
        profile = await _profile(db_session, owner)
        response = await client.post(
            "/push/subscriptions",
            json=_body(profile, auth=AUTH_1 + "=="),
        )
        assert response.status_code == 204

    async def test_blank_fields_are_rejected(self, client, db_session, owner):
        profile = await _profile(db_session, owner)
        for field in ("endpoint", "p256dh", "auth"):
            response = await client.post(
                "/push/subscriptions", json=_body(profile, **{field: "  "})
            )
            assert response.status_code == 422, field

    async def test_unknown_profile_is_404(self, client, owner):
        response = await client.post(
            "/push/subscriptions",
            json={
                "profile_id": 999999,
                "endpoint": ENDPOINT,
                "p256dh": KEY_1,
                "auth": AUTH_1,
            },
        )
        assert response.status_code == 404


class TestUnsubscribe:
    async def test_deletes_only_the_named_endpoint(self, client, db_session, owner):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=ENDPOINT + "2")
        )

        response = await client.request(
            "DELETE",
            "/push/subscriptions",
            json={"profile_id": profile.id, "endpoint": ENDPOINT},
        )

        assert response.status_code == 204
        [row] = await _rows(db_session, profile)
        assert row.endpoint == ENDPOINT + "2"

    async def test_unknown_endpoint_is_a_no_op_204(self, client, db_session, owner):
        profile = await _profile(db_session, owner)

        response = await client.request(
            "DELETE",
            "/push/subscriptions",
            json={"profile_id": profile.id, "endpoint": ENDPOINT + "-none"},
        )

        assert response.status_code == 204


class TestSendTest:
    async def test_sends_to_each_subscription(self, client, db_session, owner, sent):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        await client.post(
            "/push/subscriptions", json=_body(profile, endpoint=ENDPOINT + "2")
        )

        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 204
        assert sorted(endpoint for endpoint, _ in sent) == [ENDPOINT, ENDPOINT + "2"]
        assert set(sent[0][1]) == {"title", "body", "url"}

    async def test_does_not_send_to_other_profiles(
        self, client, db_session, owner, sent
    ):
        mine = await _profile(db_session, owner)
        other = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(other))

        await client.post("/push/test", json={"profile_id": mine.id})

        assert sent == []

    @pytest.mark.parametrize("gone", [404, 410])
    async def test_gone_subscriptions_are_deleted(
        self, client, db_session, owner, sent, gone
    ):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        sent.status = gone

        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 502
        assert await _rows(db_session, profile) == []

    async def test_other_failures_keep_the_subscription(
        self, client, db_session, owner, sent
    ):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        sent.status = 500

        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 502
        assert response.json()["detail"] == (
            "The push service did not accept the notification"
        )
        assert len(await _rows(db_session, profile)) == 1

    async def test_409_when_the_profile_has_no_subscription(
        self, client, db_session, owner, sent
    ):
        profile = await _profile(db_session, owner)

        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "No device is registered for notifications on this profile"
        )
        assert sent == []

    async def test_404_when_unconfigured(self, client, db_session, owner, monkeypatch):
        profile = await _profile(db_session, owner)
        monkeypatch.setattr(settings, "vapid_subject", "")

        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 404

    async def test_is_rate_limited(self, client, db_session, owner, sent):
        profile = await _profile(db_session, owner)
        await client.post("/push/subscriptions", json=_body(profile))
        limit = rate_limit.LIMITS["push_test"].limit

        for _ in range(limit):
            response = await client.post("/push/test", json={"profile_id": profile.id})
            assert response.status_code == 204
        response = await client.post("/push/test", json={"profile_id": profile.id})

        assert response.status_code == 429
