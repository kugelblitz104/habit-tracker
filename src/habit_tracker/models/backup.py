"""Pydantic models for a full-profile backup (export / import).

A backup is a single self-describing JSON document holding one profile and
every entity that hangs off it — projects, tasks (and subtasks), countdowns,
time entries, habits, trackers, calendar connections, and integration
connections. It is the portable format for moving a profile between instances
(e.g. the hosted app to an on-prem server), which per-entity endpoints don't
cover.

Cross-references keep the *source* row ids: each record carries its original
``id``, and foreign keys (``project_id``, ``parent_id``, ``task_id``,
``habit_id``) reference those originals. The importer remaps every id to the
freshly-created rows, so the source and target databases never need to agree on
primary keys.

Two things are deliberately NOT round-tripped:

- Integration PATs. The token is encrypted with a key derived from the source
  instance's secret, so it is meaningless on another instance. Only the
  connection's configuration is exported (``has_token`` records that one was
  set); the importer recreates the connection disabled and tokenless for the
  user to re-enter its PAT.
- Calendar ICS caches (``cached_ics``/``etag``/``last_fetched_at``). These are
  refetched from the feed URL, so exporting them would only bloat the file.
"""

from datetime import date, datetime, time

from pydantic import BaseModel

from habit_tracker.models._base import _FromORM

# Bump VERSION on any breaking change to the document shape; FORMAT lets the
# importer reject an unrelated JSON file with a clear message.
BACKUP_FORMAT = "habit-tracker-profile-backup"
BACKUP_VERSION = 1


class ProfileSettings(_FromORM):
    """The profile's own fields (everything except id / owner / timestamps)."""

    name: str
    color_start: str
    color_end: str
    habits_enabled: bool
    countdowns_enabled: bool
    insights_enabled: bool
    calendar_enabled: bool
    publish_to_azure: bool
    default_landing: str
    week_start_monday: bool
    use_habit_color_accent: bool
    show_estimated_effort: bool
    pomodoro_work_minutes: int
    pomodoro_break_minutes: int
    pomodoro_long_break_minutes: int
    pomodoro_cycles: int


class ProjectBackup(_FromORM):
    id: int
    name: str
    color: str
    notes: str | None = None
    archived: bool = False
    created_date: datetime | None = None
    updated_date: datetime | None = None


class TaskBackup(_FromORM):
    id: int
    project_id: int | None = None
    parent_id: int | None = None
    title: str
    notes: str | None = None
    priority: int = 0
    due_date: date | None = None
    due_time: time | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    status: int = 0
    block_reason: str | None = None
    source: str | None = None
    external_ref: str | None = None
    external_url: str | None = None
    estimated_effort: int | None = None
    closed_date: datetime | None = None
    created_date: datetime | None = None
    updated_date: datetime | None = None
    sort_order: int = 0


class CountdownBackup(_FromORM):
    id: int
    task_id: int | None = None
    title: str
    target_date: date
    target_time: time | None = None
    category: str | None = None
    color: str | None = None
    repeat: str = "none"
    show_occurrence: bool = False
    created_date: datetime | None = None
    updated_date: datetime | None = None


class TimeEntryBackup(_FromORM):
    id: int
    task_id: int | None = None
    project_id: int | None = None
    kind: int = 0
    label: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    note: str | None = None
    created_date: datetime | None = None
    updated_date: datetime | None = None


class HabitBackup(_FromORM):
    id: int
    name: str
    question: str
    category: str | None = None
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: str | None = None
    archived: bool = False
    sort_order: int = 0
    created_date: datetime | None = None
    updated_date: datetime | None = None


class TrackerBackup(_FromORM):
    id: int
    habit_id: int
    dated: date
    status: int = 2
    note: str | None = None
    created_date: datetime | None = None
    updated_date: datetime | None = None


class CalendarConnectionBackup(_FromORM):
    id: int
    name: str
    color: str
    url: str
    provider: str | None = None
    enabled: bool = True
    created_date: datetime | None = None
    updated_date: datetime | None = None


class IntegrationConnectionBackup(_FromORM):
    id: int
    provider: str
    name: str
    organization: str | None = None
    project: str | None = None
    work_item_type: str | None = None
    base_url: str | None = None
    default_repo: str | None = None
    enabled: bool = True
    # Whether the source connection had a PAT stored (the token itself is never
    # exported); surfaced so the import summary can flag re-auth.
    has_token: bool = False


class ProfileBackup(BaseModel):
    """A complete, portable snapshot of one profile and its data."""

    format: str = BACKUP_FORMAT
    version: int = BACKUP_VERSION
    exported_at: datetime
    profile: ProfileSettings
    projects: list[ProjectBackup] = []
    tasks: list[TaskBackup] = []
    countdowns: list[CountdownBackup] = []
    time_entries: list[TimeEntryBackup] = []
    habits: list[HabitBackup] = []
    trackers: list[TrackerBackup] = []
    calendar_connections: list[CalendarConnectionBackup] = []
    integration_connections: list[IntegrationConnectionBackup] = []


class ImportSummary(BaseModel):
    """Per-entity counts of what an import created, plus any warnings."""

    success: bool
    profile_id: int
    profile_name: str
    projects_imported: int = 0
    tasks_imported: int = 0
    subtasks_imported: int = 0
    countdowns_imported: int = 0
    time_entries_imported: int = 0
    habits_imported: int = 0
    trackers_imported: int = 0
    calendar_connections_imported: int = 0
    integration_connections_imported: int = 0
    warnings: list[str] = []
