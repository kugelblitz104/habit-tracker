"""Constants used across the application."""
from datetime import date, timedelta
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
    4 = needs info
    5 = deferred
    6 = done
    7 = cancelled
    """

    OPEN = 0
    IN_PROGRESS = 1
    SCHEDULED = 2
    BLOCKED = 3
    NEEDS_INFO = 4
    DEFERRED = 5
    DONE = 6
    CANCELLED = 7


class TaskBand(str, Enum):
    """Computed urgency band for a task. Never stored - derived from
    status + priority + due date via compute_band()."""

    NOW = "now"
    SOON = "soon"
    WHENEVER = "whenever"
    HIDDEN = "hidden"


def compute_band(
    status: int,
    priority: int,
    due_date: date | None,
    today: date | None = None,
) -> TaskBand:
    """Compute the urgency band for a task. First match wins:

    - hidden: status is DONE or CANCELLED
    - now: overdue, due today, or priority == 3
    - soon: due within the next 7 days, or priority == 2
    - whenever: everything else
    """
    if today is None:
        today = date.today()

    if status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        return TaskBand.HIDDEN
    if (due_date is not None and due_date <= today) or priority == 3:
        return TaskBand.NOW
    if (due_date is not None and due_date <= today + timedelta(days=7)) or priority == 2:
        return TaskBand.SOON
    return TaskBand.WHENEVER
