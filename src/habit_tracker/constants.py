"""Constants used across the application."""

from enum import Enum


class TrackerStatus(int, Enum):
    """Status of a tracker entry.

    0 = not completed
    1 = skipped
    2 = completed
    """

    NOT_COMPLETED = 0
    SKIPPED = 1
    COMPLETED = 2


class TaskStatus(int, Enum):
    """Status of a task.

    0 = open
    1 = in progress
    2 = scheduled
    3 = blocked
    4 = needs info (waiting on an answer or a clarification, from me or others)
    5 = deferred
    6 = done
    7 = cancelled
    8 = pending (work done on my end, waiting for others to validate/close)

    9 was "unclear" and was merged into NEEDS_INFO. The value is free for a
    future status, and stays free only because both halves hold: the migration
    rewrote every stored 9 to 4, and TaskBackup rejects a 9 rather than storing
    one. Drop either and a stale 9 survives to be absorbed by whatever claims
    the value next.
    """

    OPEN = 0
    IN_PROGRESS = 1
    SCHEDULED = 2
    BLOCKED = 3
    NEEDS_INFO = 4
    DEFERRED = 5
    DONE = 6
    CANCELLED = 7
    PENDING = 8


# The two statuses that close a task. Shared by the list endpoint's default
# filter, the closed-task ordering and the Markdown export's sectioning.
CLOSED_STATUSES = (TaskStatus.DONE.value, TaskStatus.CANCELLED.value)


class TimeEntryKind(int, Enum):
    """How a time entry was tracked.

    0 = stopwatch (free-running elapsed timer)
    1 = pomodoro (fixed work interval)
    """

    STOPWATCH = 0
    POMODORO = 1


class IntegrationProvider(str, Enum):
    """External task-tracker an integration connection talks to."""

    AZURE_DEVOPS = "azure_devops"
    GITHUB = "github"


class TaskPriority(int, Enum):
    """Priority of a task. Field annotations stay plain `int` - this enum is
    for validators and label maps only, never a field type (which would add
    an `enum` array to that property's JSON Schema)."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class DefaultLanding(str, Enum):
    """A profile's default landing page."""

    TODAY = "today"
    HABITS = "habits"


class DayQuality(str, Enum):
    """How a day felt, for the daily journal's check-in.

    Deliberately not a 1-5 scale: these name what a day was, so a day can
    be productive and still tiring and the writer picks whichever they
    would say first. Declaration order runs positive to negative and is
    the order a picker should render them in.

    The Obsidian importer maps the two non-descript words in the existing
    history onto these: "meh" and "mid" become GOOD, "bad" and "poor"
    become ROUGH.
    """

    GREAT = "great"
    GOOD = "good"
    EXCITING = "exciting"
    PRODUCTIVE = "productive"
    QUIET = "quiet"
    STEADY = "steady"
    BUSY = "busy"
    MIXED = "mixed"
    TIRING = "tiring"
    DRAINING = "draining"
    FRUSTRATING = "frustrating"
    STRESSFUL = "stressful"
    ROUGH = "rough"


class CountdownRepeat(str, Enum):
    """Recurrence rule for a countdown, anchored on its target_date.

    "monthly_weekday" recurs on the Nth weekday of the month (e.g. 3rd
    Monday), with N + weekday derived from the anchor target_date; the rest
    are calendar rules (same day-of-month / same month+day).
    """

    NONE = "none"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MONTHLY_WEEKDAY = "monthly_weekday"
    YEARLY = "yearly"
