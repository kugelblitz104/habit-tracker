"""Loop Habit Tracker file format: its 20-color palette, timestamps, weekday
mask, repetition values, and the mapping between Loop's SQLite rows and this
app's habit/tracker field values, in both directions.

Everything here takes and returns plain data, so it needs no database session
and no SQLite file. Lives in services/ rather than models/ because this is
Loop's own file-format data (not a Pydantic request/response shape).
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any

from habit_tracker.constants import TrackerStatus

LOOP_HABIT_COLORS = [
    "#D32F2F",  #  0 red
    "#E64A19",  #  1 deep orange
    "#F57C00",  #  2 orange
    "#FF8F00",  #  3 amber
    "#F9A825",  #  4 yellow
    "#AFB42B",  #  5 lime
    "#7CB342",  #  6 light green
    "#388E3C",  #  7 green
    "#00897B",  #  8 teal
    "#00ACC1",  #  9 cyan
    "#039BE5",  # 10 light blue
    "#1976D2",  # 11 blue
    "#303F9F",  # 12 indigo
    "#5E35B1",  # 13 deep purple
    "#8E24AA",  # 14 purple
    "#D81B60",  # 15 pink
    "#5D4037",  # 16 brown
    "#303030",  # 17 dark grey
    "#757575",  # 18 grey
    "#aaaaaa",  # 19 light grey
]


def map_color(color_index: int) -> str:
    """Map Loop Habit Tracker color index to hex color code."""
    if 0 <= color_index < len(LOOP_HABIT_COLORS):
        return LOOP_HABIT_COLORS[color_index]
    # Default to blue if index is out of range
    return "#1976D2"


def reverse_map_color(hex_color: str) -> int:
    """Map hex color code back to Loop Habit Tracker color index."""
    hex_upper = hex_color.upper()
    for index, color in enumerate(LOOP_HABIT_COLORS):
        if color.upper() == hex_upper:
            return index
    # Default to blue (index 11) if not found
    return 11


def date_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime to Loop Habit Tracker timestamp.
    Loop Habit Tracker uses milliseconds since epoch at midnight UTC.
    """
    return int(dt.replace(tzinfo=UTC).timestamp() * 1000)


def timestamp_to_date(timestamp: int) -> datetime:
    """
    Convert Loop Habit Tracker timestamp to datetime.

    Loop stores repetition timestamps as milliseconds since epoch at midnight
    UTC of the tracked day, so decode in UTC - a server-local decode shifts
    every date back one day in any negative-offset timezone.
    """
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC)


def map_repetition_value(value: int) -> TrackerStatus | None:
    """
    Map a Loop Habit Tracker repetition value to a TrackerStatus.

    Loop's value semantics vary by app version:
    - 0 = not done (all versions) - never imported
    - 1 = skipped (older exports) - SKIPPED
    - 2 = done / YES_MANUAL - COMPLETED
    - 3 = SKIP (Loop 2.x) - SKIPPED
    - >3 = numerical habits store amount x 1000 - COMPLETED

    Returns None for values that should not create a tracker. Writing the raw
    value into Tracker.status would corrupt the column for 3 and numerical
    amounts, so everything is clamped to the app's enum here.
    """
    if value <= 0:
        return None
    if value in (1, 3):
        return TrackerStatus.SKIPPED
    return TrackerStatus.COMPLETED


# Loop packs its weekdays Saturday-first (bit 0 = Saturday ... bit 6 = Friday);
# Habit.reminder_days is Monday-first, so Loop bit i is our bit (i + 5) % 7.
def mask_from_loop(loop_mask: int) -> int:
    """Convert a Loop reminder_days mask to Habit.reminder_days."""
    if not loop_mask & 127:
        return 127  # Loop treats an empty day set as every day
    return sum(1 << ((i + 5) % 7) for i in range(7) if loop_mask >> i & 1)


def mask_to_loop(mask: int) -> int:
    """Convert Habit.reminder_days to a Loop reminder_days mask."""
    return sum(1 << ((j + 2) % 7) for j in range(7) if mask >> j & 1)


def loop_reminder_time(hour: int | None, minute: int | None) -> time | None:
    """Loop's reminder_hour/reminder_min as a time, or None when Loop's reminder
    is off (a null hour) or the values are out of range."""
    if hour is None or not 0 <= hour <= 23 or not 0 <= (minute or 0) <= 59:
        return None
    return time(hour, minute or 0)


def habit_fields_from_loop(row: Mapping[str, Any]) -> dict[str, Any]:
    """Habit column values for one row of Loop's Habits table.

    Covers every Habit column the file determines; the caller adds profile_id,
    slug and sort_order. Missing or empty Loop values fall back to defaults.
    """
    name = row["name"] or "Unnamed Habit"
    reminder_time = loop_reminder_time(row["reminder_hour"], row["reminder_min"])
    return {
        "name": name,
        "question": row["question"] or f"Did you {name.lower()} today?",
        "color": map_color(row["color"] or 0),
        "frequency": row["freq_num"] or 1,
        "range": row["freq_den"] or 1,
        "reminder": reminder_time is not None,
        "reminder_time": reminder_time,
        "reminder_days": (
            mask_from_loop(row["reminder_days"]) if reminder_time is not None else 127
        ),
        "notes": row["description"],
        "archived": bool(row["archived"]),
    }


def tracker_fields_from_loop(
    timestamp: int, value: int, notes: str | None
) -> dict[str, Any]:
    """Tracker column values for one row of Loop's Repetitions table.

    `status` is None when Loop's value means "not done", which creates no
    tracker. The caller adds habit_id.
    """
    return {
        "dated": timestamp_to_date(timestamp).date(),
        "status": map_repetition_value(value),
        "note": notes,
    }


def loop_habit_row(
    *,
    name: str,
    question: str,
    color: str,
    frequency: int,
    range: int,
    notes: str | None,
    archived: bool,
    reminder: bool,
    reminder_time: time | None,
    reminder_days: int,
    position: int,
    habit_uuid: str,
) -> tuple[Any, ...]:
    """Values for one Loop Habits INSERT, in the column order of the export's
    INSERT statement (archived ... uuid). Takes a habit's field values."""
    # Loop reads a non-null hour as "reminder on", so an off reminder, or one
    # with no time, is written as NULL.
    reminder_time = reminder_time if reminder else None
    return (
        1 if archived else 0,
        reverse_map_color(color),
        notes,
        range,  # freq_den
        frequency,  # freq_num
        0,  # highlight
        name,
        position,
        reminder_time.hour if reminder_time else None,
        reminder_time.minute if reminder_time else None,
        mask_to_loop(reminder_days) if reminder_time else 127,
        0,  # type (boolean habit)
        0,  # target_type
        0.0,  # target_value
        "",  # unit
        question,
        habit_uuid,
    )


def loop_repetition_row(
    loop_habit_id: int, dated: date, status: int, note: str | None
) -> tuple[int, int, int, str | None] | None:
    """Values for one Loop Repetitions INSERT, or None when the tracker has
    nothing Loop can store.

    Uses Loop 2.x semantics (0 = not done, 2 = done, 3 = skip); the import
    accepts both the old 1 and the new 3 for skips, so round-trips are safe.
    """
    if status == TrackerStatus.SKIPPED:
        value = 3
    elif status == TrackerStatus.COMPLETED:
        value = 2
    elif note is not None:
        value = 0
    else:
        return None
    timestamp = date_to_timestamp(datetime.combine(dated, datetime.min.time()))
    return (loop_habit_id, timestamp, value, note)
