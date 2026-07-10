"""ICS calendar feed fetching, caching and parsing.

Read-only calendar subscriptions: each CalendarConnection stores an ICS URL
plus a small cache (raw ICS body, ETag, fetch timestamp, last error). This
module provides:

- ``fetch_ics`` / ``get_ics_fetcher``: the HTTP fetcher, exposed as a FastAPI
  dependency so tests can override it with a fake.
- ``parse_events``: pure ICS -> CalendarEventRead parsing for a single day,
  with recurrence expansion.
- ``cache_is_fresh`` / ``refresh_connection``: the cache refresh policy.
"""

import logging
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Awaitable, Callable

import httpx
import icalendar
import recurring_ical_events

from habit_tracker.models.calendar_connections import CalendarEventRead
from habit_tracker.schemas.db_models import CalendarConnection

logger = logging.getLogger(__name__)

# How long a cached ICS body is considered fresh after a SUCCESSFUL fetch
CACHE_TTL = timedelta(minutes=15)

# How long to back off before re-attempting a connection whose last fetch
# FAILED (last_error is set) - keeps a dead feed from being re-attempted
# (and hanging up to the fetch timeout) on every /events request
ERROR_RETRY_TTL = timedelta(minutes=5)

# Maximum accepted ICS feed body size (5 MB); larger feeds are treated as
# fetch failures so a runaway feed can't bloat the cache column
MAX_FEED_BYTES = 5 * 1024 * 1024

# Timeout for fetching a single ICS feed
FETCH_TIMEOUT_SECONDS = 10.0

# Some providers/CDNs (Proton, Cloudflare-fronted feeds) reject requests with
# default library User-Agents, so identify as a calendar subscriber client
FETCH_USER_AGENT = "HabitTracker-Calendar/1.0 (+ICS subscription reader)"

# (status_code, body_text, etag) - body_text is None on 304 Not Modified
IcsFetcher = Callable[[str, str | None], Awaitable[tuple[int, str | None, str | None]]]


async def fetch_ics(
    url: str, etag: str | None
) -> tuple[int, str | None, str | None]:
    """Fetch an ICS feed over HTTP.

    Sends ``If-None-Match`` when an ETag is available so unchanged feeds can
    answer 304 without a body. Returns ``(status_code, body_text, etag)``;
    ``body_text`` is None for 304 responses.
    """
    headers = {"User-Agent": FETCH_USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True
    ) as http:
        response = await http.get(url, headers=headers)
    if response.status_code == 304:
        return 304, None, etag
    return response.status_code, response.text, response.headers.get("ETag")


def get_ics_fetcher() -> IcsFetcher:
    """Dependency returning the ICS fetcher (override in tests)."""
    return fetch_ics


def _sort_key(event: CalendarEventRead) -> tuple[bool, float]:
    """All-day events first, then by start time.

    ``timestamp()`` gives a comparable float for both naive (assumed local)
    and timezone-aware datetimes, so mixed feeds don't blow up on comparison.
    """
    return (not event.all_day, event.start.timestamp())


def parse_events(
    ics_text: str,
    connection: CalendarConnection,
    target_date: date,
    tz: tzinfo | None = None,
) -> list[CalendarEventRead]:
    """Parse an ICS body into the normalized events of a single day.

    Expands recurring events (RRULE et al.) for ``target_date`` only; every
    returned event is stamped with ``event_date=target_date``. All-day
    events (DTSTART is a date, not a datetime) are represented as naive
    midnight with ``all_day=True``; timed events keep whatever timezone offset
    the feed provides.

    When ``tz`` is given, the day runs from midnight to midnight IN THAT
    timezone (aware datetimes are passed to the recurrence expander), so a
    UTC-encoded evening event lands on the viewer's local day instead of the
    feed's. Without ``tz`` the plain-date boundary is used, which the expander
    interprets in each event's own timezone (legacy behavior).

    Raises ValueError for malformed feeds so callers can report a
    connection-level error instead of failing the whole response.
    """
    if tz is not None:
        day_start: date | datetime = datetime.combine(target_date, time.min, tzinfo=tz)
        day_end: date | datetime = day_start + timedelta(days=1)
    else:
        day_start = target_date
        day_end = target_date + timedelta(days=1)
    try:
        calendar = icalendar.Calendar.from_ical(ics_text)
        occurrences = recurring_ical_events.of(calendar).between(day_start, day_end)
    except Exception as exc:
        raise ValueError(f"could not parse ICS feed: {exc}") from exc

    events: list[CalendarEventRead] = []
    for occurrence in occurrences:
        dtstart = occurrence.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        dtend = occurrence.get("DTEND")
        end = dtend.dt if dtend is not None else None

        all_day = not isinstance(start, datetime)
        if all_day:
            # DTSTART is a plain date: represent as (naive) midnight
            start = datetime.combine(start, time.min)
            if end is not None and not isinstance(end, datetime):
                end = datetime.combine(end, time.min)

        summary = occurrence.get("SUMMARY")
        location = occurrence.get("LOCATION")

        events.append(
            CalendarEventRead(
                connection_id=connection.id,
                calendar_name=connection.name,
                color=connection.color,
                title=str(summary) if summary else "(untitled)",
                location=str(location) if location else None,
                all_day=all_day,
                event_date=target_date,
                start=start,
                end=end,
            )
        )

    events.sort(key=_sort_key)
    return events


def cache_is_fresh(connection: CalendarConnection, now: datetime) -> bool:
    """Dual-TTL freshness check on the last fetch ATTEMPT time.

    ``last_fetched_at`` records the last fetch attempt (successful or not).
    A successfully fetched cache (no ``last_error``) is fresh for CACHE_TTL
    (15 min); after a FAILED attempt (``last_error`` set) the connection is
    not re-attempted for ERROR_RETRY_TTL (5 min), so a dead feed can't hang
    every /events request up to the fetch timeout.
    """
    if connection.last_fetched_at is None:
        return False
    ttl = ERROR_RETRY_TTL if connection.last_error is not None else CACHE_TTL
    return now - connection.last_fetched_at < ttl


def _record_failure(
    connection: CalendarConnection, now: datetime, error: str
) -> str:
    """Record a failed fetch attempt: keep the stale cache, set last_error,
    and stamp the attempt time so the failure backoff (ERROR_RETRY_TTL)
    applies. Returns the error string for the caller to surface."""
    connection.last_error = error
    connection.last_fetched_at = now
    return error


async def refresh_connection(
    connection: CalendarConnection, fetcher: IcsFetcher
) -> str | None:
    """Refresh a connection's ICS cache if it is stale.

    Policy:
    - fresh cache (see ``cache_is_fresh``: 15 min after success, 5 min
      failure backoff) -> no fetch
    - 200 with a parseable, <=5 MB body -> store body + etag + now, clear
      last_error
    - 200 with an oversized or unparseable body -> treated as a failure:
      KEEP stale cache, set last_error, stamp the attempt time
    - 304 -> keep cached body, bump last_fetched_at, clear last_error
    - non-2xx / exception -> KEEP stale cache, set last_error, stamp the
      attempt time (failure backoff)

    Mutates the connection's cache columns in place (caller commits).
    Returns a human-readable error string when the fetch failed, else None.
    """
    now = datetime.now()
    if cache_is_fresh(connection, now):
        return None

    try:
        status_code, body, etag = await fetcher(connection.url, connection.etag)
    except Exception as exc:
        logger.warning(
            "ICS fetch failed for connection %s (%s): %s",
            connection.id,
            connection.url,
            exc,
        )
        return _record_failure(
            connection, now, f"fetch failed ({type(exc).__name__})"
        )

    if status_code == 200 and body is not None:
        if len(body.encode("utf-8", errors="ignore")) > MAX_FEED_BYTES:
            return _record_failure(connection, now, "feed too large")
        # Validate BEFORE committing to the cache so a "200 OK" HTML
        # maintenance page can't clobber a good ICS cache
        try:
            icalendar.Calendar.from_ical(body)
        except Exception:
            return _record_failure(
                connection, now, "feed returned unparseable content"
            )
        connection.cached_ics = body
        connection.etag = etag
        connection.last_fetched_at = now
        connection.last_error = None
        return None
    if status_code == 304:
        # Feed unchanged - keep the cached body, just note it is still fresh
        connection.last_fetched_at = now
        connection.last_error = None
        return None

    return _record_failure(connection, now, f"HTTP {status_code}")
