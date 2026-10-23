"""In-process sliding-window limiter for the auth endpoints.

For each key (who is being limited, for what) it keeps the timestamps of recent
attempts. An attempt is allowed while fewer than `limit` of them fall inside the
last `window` seconds. The window slides with the clock rather than resetting
on fixed boundaries, so a burst straddling a minute mark is still caught.

State lives in this process, so it is only correct while the API runs a single
uvicorn worker (the Dockerfile CMD). Behind a reverse proxy the client IP comes
from CLIENT_IP_HEADER or FORWARDED_ALLOW_IPS, or every client shares the
proxy's IP. Limits are configured in rate_limits.toml.
"""

import time
import tomllib
from collections import deque
from collections.abc import Awaitable, Callable
from math import ceil
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException, Request, status

from habit_tracker.core.config import settings


class Limit(NamedTuple):
    """At most `limit` attempts per `window` seconds."""

    limit: int
    window: int


# {"login": Limit(10, 60), ...}, one entry per [section] of rate_limits.toml.
with (Path(__file__).with_name("rate_limits.toml")).open("rb") as f:
    LIMITS = {
        name: Limit(cfg["limit"] + settings.rate_limit_extra, cfg["window_seconds"])
        for name, cfg in tomllib.load(f).items()
    }

# Key -> attempt timestamps, oldest first. Keys are prefixed with what is being
# limited ("login:1.2.3.4", "login-account:jjones:1.2.3.4"), so one dict holds
# every limit. A deque because expired timestamps come off the front, which a
# deque does in constant time and a list does not. Timestamps are
# time.monotonic(), which never jumps when the system clock is changed.
_hits: dict[str, deque[float]] = {}

# Past this many keys, record() sweeps out keys with no live timestamps.
_MAX_KEYS = 10_000
# No limit looks further back than its window, so older timestamps are dead.
_MAX_AGE = max(lim.window for lim in LIMITS.values())


def reset() -> None:
    """Forget every attempt. For tests."""
    _hits.clear()


def _recent(key: str, window: int, now: float) -> deque[float]:
    """Return `key`'s timestamps inside the last `window` seconds.

    Drops expired ones from the front as it goes; since the deque is in time
    order, it can stop at the first timestamp still inside the window.
    """
    hits = _hits.setdefault(key, deque())
    while hits and hits[0] <= now - window:
        hits.popleft()
    return hits


def retry_after(key: str, lim: Limit) -> int:
    """Seconds until `key` may act again, or 0 if it may act now.

    Only checks; call record() to count the attempt. When blocked, the wait is
    until the oldest attempt in the window expires, freeing one slot.
    """
    now = time.monotonic()
    hits = _recent(key, lim.window, now)
    if len(hits) < lim.limit:
        return 0
    return ceil(hits[0] + lim.window - now)


def record(key: str) -> None:
    """Count one attempt for `key` now."""
    now = time.monotonic()
    if len(_hits) > _MAX_KEYS:
        expired = [k for k, h in _hits.items() if not h or h[-1] <= now - _MAX_AGE]
        for k in expired:
            del _hits[k]
    _hits.setdefault(key, deque()).append(now)


def clear(key: str) -> None:
    """Forget every attempt for `key`, e.g. after a successful login."""
    _hits.pop(key, None)


def too_many(wait: int) -> HTTPException:
    """The 429 response. Retry-After is at least 1 so it never says "retry now"."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many attempts. Try again later.",
        headers={"Retry-After": str(max(wait, 1))},
    )


def client_ip(request: Request) -> str:
    """The caller's IP: CLIENT_IP_HEADER when configured and present, else the
    connection's peer address."""
    if settings.client_ip_header:
        ip = request.headers.get(settings.client_ip_header, "").strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


def limit_by_ip(name: str) -> Callable[[Request], Awaitable[None]]:
    """Build a route dependency enforcing LIMITS[name] per client IP.

    Use as `dependencies=[Depends(limit_by_ip("login"))]`. The limit is looked
    up once, when routes are registered, so an unknown name fails at startup.
    FastAPI runs the returned function before each request: it raises 429 when
    the caller is over the limit, otherwise counts the request.
    """
    lim = LIMITS[name]

    async def dependency(request: Request) -> None:
        key = f"{name}:{client_ip(request)}"
        wait = retry_after(key, lim)
        if wait:
            raise too_many(wait)
        record(key)

    return dependency
