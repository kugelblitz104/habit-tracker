"""Web Push sender: RFC 8291 payload encryption and RFC 8292 (VAPID) auth over httpx.

`pywebpush` does the same job but brings `requests` and `aiohttp` with it;
`http-ece` and `py-vapid` are its two cryptographic halves and run on the
`httpx` the app already has.
"""

import json
import logging
import time
from urllib.parse import urlsplit

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02, b64urldecode, b64urlencode

from habit_tracker.core.config import settings
from habit_tracker.models._validators import validate_push_endpoint
from habit_tracker.schemas.db_models import PushSubscription
from habit_tracker.services.notifications import CONFIG

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Whether Web Push can run: a VAPID key, and the subject push services
    need to contact the operator."""
    return bool(settings.vapid_private_key and settings.vapid_subject)


def _decode(value: str) -> bytes:
    """Unpadded base64url text to bytes (py_vapid's decoder wants bytes in)."""
    return b64urldecode(value.encode())


def _vapid() -> Vapid02:
    return Vapid02.from_string(settings.vapid_private_key)


def vapid_public_key() -> str:
    """The VAPID public key as the browser's `applicationServerKey`: the
    uncompressed P-256 point, base64url."""
    public_key = _vapid().public_key
    assert public_key is not None  # set whenever a private key is loaded
    point = public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64urlencode(point)


def _encrypt(subscription: PushSubscription, payload: dict) -> bytes:
    """aes128gcm-encrypt `payload` to the subscription.

    Each call uses a fresh ephemeral key pair, and `http_ece` draws a random
    salt, so no two messages share key material.
    """
    return http_ece.encrypt(
        json.dumps(payload).encode(),
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_decode(subscription.p256dh),
        auth_secret=_decode(subscription.auth),
        version="aes128gcm",
    )


async def send(
    subscription: PushSubscription,
    payload: dict,
    *,
    client: httpx.AsyncClient | None = None,
) -> int:
    """POST one encrypted notification and return the push service's HTTP status.

    A 404 or 410 means the browser has dropped the subscription; the caller
    decides what to do with it. Network failures raise `httpx.HTTPError`. A
    stored endpoint off the push-host allowlist is logged and not contacted;
    it answers 410 so the caller deletes it.
    `client` is for tests; production opens one per call, which is cheap at
    reminder volumes.
    """
    try:
        validate_push_endpoint(subscription.endpoint)
    except ValueError:
        logger.error(
            "Subscription %s endpoint is not on the push host allowlist; skipped",
            subscription.id,
        )
        return 410
    parts = urlsplit(subscription.endpoint)
    push = CONFIG["push"]
    claims = {
        "sub": settings.vapid_subject,
        "aud": f"{parts.scheme}://{parts.hostname}",
        "exp": int(time.time()) + push["vapid_token_hours"] * 3600,
    }
    headers = {
        **_vapid().sign(claims),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(push["ttl_seconds"]),
    }
    content = _encrypt(subscription, payload)
    if client is not None:
        response = await client.post(
            subscription.endpoint, content=content, headers=headers
        )
    else:
        async with httpx.AsyncClient(timeout=push["request_timeout_seconds"]) as own:
            response = await own.post(
                subscription.endpoint, content=content, headers=headers
            )
    return response.status_code
