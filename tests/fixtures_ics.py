"""Shared ICS fixture data and fake fetcher for calendar-connection tests.

Pulled out of test_calendar_connections.py so any other test module that
needs a canned ICS feed (or a fake ``get_ics_fetcher`` override) can reuse it
without duplicating the literal or the fake.
"""

from habit_tracker.main import app
from habit_tracker.services.calendar_events import get_ics_fetcher

# Canned feed containing, relative to 2026-07-09 (a Thursday):
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
