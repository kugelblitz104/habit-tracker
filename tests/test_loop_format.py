"""Plain-data tests for services/loop_format: the mapping between Loop's rows
and this app's habit/tracker field values, in both directions.

No database and no SQLite file; the upload/export endpoints are covered over
HTTP in test_imports.py.
"""

from datetime import date, time

import pytest

from habit_tracker.constants import TrackerStatus
from habit_tracker.services.loop_format import (
    habit_fields_from_loop,
    loop_habit_row,
    loop_repetition_row,
    tracker_fields_from_loop,
)

LOOP_HABIT = {
    "name": "Read",
    "question": "Did you read?",
    "color": 3,
    "freq_num": 3,
    "freq_den": 7,
    "reminder_hour": 6,
    "reminder_min": 30,
    "reminder_days": 0b11,  # Saturday + Sunday
    "description": "ten pages",
    "archived": 1,
}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {},
            {
                "name": "Read",
                "question": "Did you read?",
                "color": "#FF8F00",
                "frequency": 3,
                "range": 7,
                "reminder": True,
                "reminder_time": time(6, 30),
                "reminder_days": 0b1100000,  # Saturday + Sunday, Monday-first
                "notes": "ten pages",
                "archived": True,
            },
        ),
        (
            {
                "name": None,
                "question": None,
                "color": None,
                "freq_num": None,
                "freq_den": None,
                "reminder_hour": None,
                "reminder_min": None,
                "description": None,
                "archived": None,
            },
            {
                "name": "Unnamed Habit",
                "question": "Did you unnamed habit today?",
                "color": "#D32F2F",
                "frequency": 1,
                "range": 1,
                "reminder": False,
                "reminder_time": None,
                "reminder_days": 127,
                "notes": None,
                "archived": False,
            },
        ),
        (
            {"reminder_hour": 24},
            {"reminder": False, "reminder_time": None, "reminder_days": 127},
        ),
        ({"color": 99}, {"color": "#1976D2"}),
    ],
)
def test_habit_fields_from_loop(overrides, expected):
    fields = habit_fields_from_loop({**LOOP_HABIT, **overrides})
    assert expected.items() <= fields.items()


@pytest.mark.parametrize(
    ("timestamp", "value", "notes", "expected"),
    [
        (1748736000000, 2, "n", (date(2025, 6, 1), TrackerStatus.COMPLETED, "n")),
        (1748736000000, 3, None, (date(2025, 6, 1), TrackerStatus.SKIPPED, None)),
        (1748736000000, 1, None, (date(2025, 6, 1), TrackerStatus.SKIPPED, None)),
        (1748736000000, 5000, None, (date(2025, 6, 1), TrackerStatus.COMPLETED, None)),
        (1748736000000, 0, "x", (date(2025, 6, 1), None, "x")),
    ],
)
def test_tracker_fields_from_loop(timestamp, value, notes, expected):
    fields = tracker_fields_from_loop(timestamp, value, notes)
    assert (fields["dated"], fields["status"], fields["note"]) == expected


def habit_kwargs(**overrides):
    return {
        "name": "Read",
        "question": "Did you read?",
        "color": "#ff8f00",
        "frequency": 3,
        "range": 7,
        "notes": "ten pages",
        "archived": True,
        "reminder": True,
        "reminder_time": time(6, 30),
        "reminder_days": 0b1100000,
        "position": 4,
        "habit_uuid": "u-1",
        **overrides,
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {},
            (1, 3, "ten pages", 7, 3, 0, "Read", 4, 6, 30, 0b11)
            + (0, 0, 0.0, "", "Did you read?", "u-1"),
        ),
        (
            {"reminder": False, "archived": False, "color": "#123456"},
            (0, 11, "ten pages", 7, 3, 0, "Read", 4, None, None, 127)
            + (0, 0, 0.0, "", "Did you read?", "u-1"),
        ),
        (
            {"reminder_time": None},
            (1, 3, "ten pages", 7, 3, 0, "Read", 4, None, None, 127)
            + (0, 0, 0.0, "", "Did you read?", "u-1"),
        ),
    ],
)
def test_loop_habit_row(overrides, expected):
    assert loop_habit_row(**habit_kwargs(**overrides)) == expected


@pytest.mark.parametrize(
    ("status", "note", "expected"),
    [
        (TrackerStatus.COMPLETED, "n", (9, 1748736000000, 2, "n")),
        (TrackerStatus.SKIPPED, None, (9, 1748736000000, 3, None)),
        (TrackerStatus.NOT_COMPLETED, "why", (9, 1748736000000, 0, "why")),
        (TrackerStatus.NOT_COMPLETED, None, None),
    ],
)
def test_loop_repetition_row(status, note, expected):
    assert loop_repetition_row(9, date(2025, 6, 1), status, note) == expected
