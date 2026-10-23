"""The Web Push sender: payload encryption (RFC 8291), VAPID auth, status mapping.

No network: the HTTP client is given an `httpx.MockTransport`, and the
subscription is a real P-256 key pair generated here, so the ciphertext is
decrypted with the same library the sender encrypts with.
"""

import json
import time

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from py_vapid import Vapid02, b64urldecode, b64urlencode

from habit_tracker.core.config import settings
from habit_tracker.schemas.db_models import PushSubscription
from habit_tracker.services import web_push
from habit_tracker.services.notifications import CONFIG

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def _raw_private_key(vapid: Vapid02) -> str:
    numbers = vapid.private_key.private_numbers()
    return b64urlencode(numbers.private_value.to_bytes(32, "big"))


@pytest.fixture
def vapid_key(monkeypatch) -> Vapid02:
    vapid = Vapid02()
    vapid.generate_keys()
    monkeypatch.setattr(settings, "vapid_private_key", _raw_private_key(vapid))
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@example.com")
    return vapid


@pytest.fixture
def browser():
    """A subscription plus the private key and auth secret behind it."""
    private = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    subscription = PushSubscription(
        endpoint=ENDPOINT, p256dh=b64urlencode(public), auth=b64urlencode(auth)
    )
    return subscription, private, auth


def _capture(status_code: int = 201):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code)

    return seen, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_payload_decrypts_with_the_subscription_key(vapid_key, browser):
    subscription, private, auth = browser
    seen, client = _capture()
    payload = {"title": "Pay rent", "body": "Due in 15 min", "url": "/tasks/pay-rent"}

    status = await web_push.send(subscription, payload, client=client)

    assert status == 201
    plain = http_ece.decrypt(
        seen[0].content, private_key=private, auth_secret=auth, version="aes128gcm"
    )
    assert json.loads(plain) == payload


async def test_each_send_uses_a_fresh_ephemeral_key_and_salt(vapid_key, browser):
    subscription, _, _ = browser
    seen, client = _capture()

    await web_push.send(subscription, {"title": "a"}, client=client)
    await web_push.send(subscription, {"title": "a"}, client=client)

    assert seen[0].content != seen[1].content
    # aes128gcm header: 16 byte salt, 4 byte record size, 1 byte key id length.
    assert seen[0].content[:16] != seen[1].content[:16]


async def test_request_headers(vapid_key, browser):
    subscription, _, _ = browser
    seen, client = _capture()

    await web_push.send(subscription, {"title": "a"}, client=client)

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == ENDPOINT
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == str(CONFIG["push"]["ttl_seconds"])
    authorization = request.headers["authorization"]
    assert authorization.startswith("vapid t=")
    assert f"k={web_push.vapid_public_key()}" in authorization


async def test_vapid_token_names_the_endpoint_origin_and_subject(vapid_key, browser):
    subscription, _, _ = browser
    seen, client = _capture()

    await web_push.send(subscription, {"title": "a"}, client=client)

    token = seen[0].headers["authorization"].split("t=")[1].split(",")[0]
    claims = json.loads(b64urldecode(token.split(".")[1].encode()))
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:ops@example.com"
    # The ES256 signature (raw r||s) verifies against the advertised public key.
    head, body, signature = token.split(".")
    raw = b64urldecode(signature.encode())
    der = utils.encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    vapid_key.public_key.verify(
        der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())
    )


async def test_vapid_audience_drops_an_explicit_default_port(vapid_key, browser):
    subscription, _, _ = browser
    subscription.endpoint = "https://fcm.googleapis.com:443/fcm/send/abc"
    seen, client = _capture()

    await web_push.send(subscription, {"title": "a"}, client=client)

    token = seen[0].headers["authorization"].split("t=")[1].split(",")[0]
    claims = json.loads(b64urldecode(token.split(".")[1].encode()))
    assert claims["aud"] == "https://fcm.googleapis.com"


async def test_vapid_token_expires_in_twelve_hours(vapid_key, browser):
    """py_vapid's default is exactly 24h, which push services with a lagging
    clock reject as too far ahead."""
    subscription, _, _ = browser
    seen, client = _capture()

    await web_push.send(subscription, {"title": "a"}, client=client)

    token = seen[0].headers["authorization"].split("t=")[1].split(",")[0]
    exp = json.loads(b64urldecode(token.split(".")[1].encode()))["exp"]
    assert abs(exp - (time.time() + 12 * 3600)) < 60


@pytest.mark.parametrize(
    ("key", "subject", "expected"),
    [("k", "mailto:a@b.c", True), ("k", "", False), ("", "mailto:a@b.c", False)],
)
def test_is_configured_needs_both_key_and_subject(monkeypatch, key, subject, expected):
    monkeypatch.setattr(settings, "vapid_private_key", key)
    monkeypatch.setattr(settings, "vapid_subject", subject)
    assert web_push.is_configured() is expected


@pytest.mark.parametrize("code", [404, 410, 500])
async def test_returns_the_push_service_status(vapid_key, browser, code):
    subscription, _, _ = browser
    _, client = _capture(code)

    assert await web_push.send(subscription, {"title": "a"}, client=client) == code


def test_public_key_matches_the_private_key(vapid_key):
    expected = b64urlencode(
        vapid_key.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )

    assert web_push.vapid_public_key() == expected
    assert len(b64urldecode(expected.encode())) == 65


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/send",
        "https://127.0.0.1/send",
        "https://internal.example/send",
        "https://fcm.googleapis.com:8443/send",
    ],
)
async def test_a_stored_endpoint_off_the_allowlist_is_not_posted_to(
    vapid_key, browser, endpoint, caplog
):
    subscription, _, _ = browser
    subscription.endpoint = endpoint
    seen, client = _capture()

    status = await web_push.send(subscription, {"title": "a"}, client=client)

    assert status == 410
    assert seen == []
    assert "allowlist" in caplog.text
