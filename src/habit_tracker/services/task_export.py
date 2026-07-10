"""Pure Markdown rendering of a profile's tasks for export.

Mirrors the shape of ``habit_stats``: the formatter takes the profile name,
the tasks, the profile's project names and ``today`` so it stays pure and
unit-testable without HTTP or a database.

Layout of the exported document:

- A header with the profile name and the export date.
- One ``##`` section per non-empty urgency band, in fixed order: Now, Soon,
  Whenever, then "Completed & cancelled" (the hidden band: done/cancelled
  tasks). Empty bands are omitted entirely.
- Each task is a checklist line (``- [x]`` only for DONE) followed by
  indented detail bullets for fields that are actually set.

Ordering matches what the app shows (the tasks list endpoint): active bands
are ordered by priority (desc), due date (asc, no due date last), then
creation date (asc); the hidden band is ordered by closed date (most recent
first).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterable, Mapping

from habit_tracker.constants import TaskBand, TaskStatus, compute_band
from habit_tracker.schemas.db_models import Task

_STATUS_LABELS = {
    TaskStatus.OPEN.value: "Open",
    TaskStatus.IN_PROGRESS.value: "In progress",
    TaskStatus.SCHEDULED.value: "Scheduled",
    TaskStatus.BLOCKED.value: "Blocked",
    TaskStatus.NEEDS_INFO.value: "Needs info",
    TaskStatus.DEFERRED.value: "Deferred",
    TaskStatus.DONE.value: "Done",
    TaskStatus.CANCELLED.value: "Cancelled",
}

_PRIORITY_LABELS = {1: "Low", 2: "Medium", 3: "High"}

# Section order and human titles; the hidden band holds done/cancelled tasks
_BAND_SECTIONS: list[tuple[TaskBand, str]] = [
    (TaskBand.NOW, "Now"),
    (TaskBand.SOON, "Soon"),
    (TaskBand.WHENEVER, "Whenever"),
    (TaskBand.HIDDEN, "Completed & cancelled"),
]


def _format_when(day: date, at: time | None) -> str:
    """Render a date with its optional time, e.g. ``2026-07-09 14:30``."""
    if at is not None:
        return f"{day.isoformat()} {at.strftime('%H:%M')}"
    return day.isoformat()


def _active_sort_key(task: Task) -> tuple:
    """Priority desc, due date asc with nulls last, creation date asc."""
    return (
        -task.priority,
        task.due_date is None,
        task.due_date or date.min,
        task.created_date,
    )


def _closed_sort_key(task: Task) -> datetime:
    """Closed date, for a most-recent-first sort of the hidden band."""
    return task.closed_date or datetime.min


def _render_task(task: Task, project_names: Mapping[int, str]) -> list[str]:
    """Render one task as a checklist line plus indented detail bullets."""
    checkbox = "x" if task.status == TaskStatus.DONE.value else " "
    lines = [f"- [{checkbox}] {task.title}"]

    if task.status not in (TaskStatus.OPEN.value, TaskStatus.DONE.value):
        lines.append(f"  - Status: {_STATUS_LABELS[task.status]}")
    if task.priority > 0:
        lines.append(f"  - Priority: {_PRIORITY_LABELS[task.priority]}")
    if task.due_date is not None:
        lines.append(f"  - Due: {_format_when(task.due_date, task.due_time)}")
    if task.scheduled_date is not None:
        lines.append(
            f"  - Scheduled: {_format_when(task.scheduled_date, task.scheduled_time)}"
        )
    project_name = (
        project_names.get(task.project_id) if task.project_id is not None else None
    )
    if project_name is not None:
        lines.append(f"  - Project: {project_name}")
    if task.block_reason:
        lines.append(f"  - Blocked: {task.block_reason}")
    if task.notes:
        lines.append("  - Notes:")
        for note_line in task.notes.splitlines():
            lines.append(f"    {note_line}".rstrip())
    return lines


def render_tasks_markdown(
    profile_name: str,
    tasks: Iterable[Task],
    project_names: Mapping[int, str],
    today: date | None = None,
) -> str:
    """Render a profile's tasks as a Markdown document.

    - ``profile_name``: shown in the document header
    - ``tasks``: all of the profile's tasks (including done/cancelled)
    - ``project_names``: project id -> name, for the Project detail line
    - ``today``: banding reference date (defaults to ``date.today()``)
    """
    if today is None:
        today = date.today()

    groups: dict[TaskBand, list[Task]] = {band: [] for band, _ in _BAND_SECTIONS}
    for task in tasks:
        band = compute_band(
            task.status,
            task.priority,
            task.due_date,
            scheduled_date=task.scheduled_date,
            today=today,
        )
        groups[band].append(task)

    lines = [f"# {profile_name} — Tasks", "", f"_Exported {today.isoformat()}_"]
    for band, title in _BAND_SECTIONS:
        group = groups[band]
        if not group:
            continue
        if band == TaskBand.HIDDEN:
            group = sorted(group, key=_closed_sort_key, reverse=True)
        else:
            group = sorted(group, key=_active_sort_key)
        lines.extend(["", f"## {title}", ""])
        for task in group:
            lines.extend(_render_task(task, project_names))
    return "\n".join(lines) + "\n"
