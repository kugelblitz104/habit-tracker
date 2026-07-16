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
    8 = pending (work done on my end, waiting for others to validate/close)
    9 = unclear (requirements are unclear / need clarification)
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
    UNCLEAR = 9


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
    scheduled_date: date | None = None,
    today: date | None = None,
) -> TaskBand:
    """Compute the urgency band for a task. First match wins:

    - hidden: status is DONE or CANCELLED
    - deferred: status is DEFERRED -> whenever (still active, never hidden;
      overrides urgency from priority / due date / scheduled date)
    - now: effective date is today or past, or priority == 3
    - soon: effective date within the next 7 days, or priority == 2
    - whenever: everything else

    The "effective date" is the earliest non-null of the task's due date and
    scheduled date (None if both are unset), so a scheduled date bands a task
    the same way a due date does.
    """
    if today is None:
        today = date.today()

    candidate_dates = [d for d in (due_date, scheduled_date) if d is not None]
    effective_date = min(candidate_dates) if candidate_dates else None

    if status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        return TaskBand.HIDDEN
    if status == TaskStatus.DEFERRED:
        return TaskBand.WHENEVER
    if (effective_date is not None and effective_date <= today) or priority == 3:
        return TaskBand.NOW
    if (
        effective_date is not None and effective_date <= today + timedelta(days=7)
    ) or priority == 2:
        return TaskBand.SOON
    return TaskBand.WHENEVER
