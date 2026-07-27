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
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

# Bump VERSION on any breaking change to the document shape; FORMAT lets the
# importer reject an unrelated JSON file with a clear message.
BACKUP_FORMAT = "habit-tracker-profile-backup"
BACKUP_VERSION = 1


class _FromORM(BaseModel):
    """Base that reads straight off SQLAlchemy ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


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
    notes: Optional[str] = None
    archived: bool = False
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class TaskBackup(_FromORM):
    id: int
    project_id: Optional[int] = None
    parent_id: Optional[int] = None
    title: str
    notes: Optional[str] = None
    priority: int = 0
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    scheduled_date: Optional[date] = None
    scheduled_time: Optional[time] = None
    status: int = 0
    block_reason: Optional[str] = None
    source: Optional[str] = None
    external_ref: Optional[str] = None
    external_url: Optional[str] = None
    estimated_effort: Optional[int] = None
    closed_date: Optional[datetime] = None
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    sort_order: int = 0


class CountdownBackup(_FromORM):
    id: int
    task_id: Optional[int] = None
    title: str
    target_date: date
    target_time: Optional[time] = None
    category: Optional[str] = None
    color: Optional[str] = None
    repeat: str = "none"
    show_occurrence: bool = False
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class TimeEntryBackup(_FromORM):
    id: int
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    kind: int = 0
    label: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    note: Optional[str] = None
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class HabitBackup(_FromORM):
    id: int
    name: str
    question: str
    category: Optional[str] = None
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: Optional[str] = None
    archived: bool = False
    sort_order: int = 0
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class TrackerBackup(_FromORM):
    id: int
    habit_id: int
    dated: date
    status: int = 2
    note: Optional[str] = None
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class CalendarConnectionBackup(_FromORM):
    id: int
    name: str
    color: str
    url: str
    provider: Optional[str] = None
    enabled: bool = True
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None


class IntegrationConnectionBackup(_FromORM):
    id: int
    provider: str
    name: str
    organization: Optional[str] = None
    project: Optional[str] = None
    work_item_type: Optional[str] = None
    base_url: Optional[str] = None
    default_repo: Optional[str] = None
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
    projects: List[ProjectBackup] = []
    tasks: List[TaskBackup] = []
    countdowns: List[CountdownBackup] = []
    time_entries: List[TimeEntryBackup] = []
    habits: List[HabitBackup] = []
    trackers: List[TrackerBackup] = []
    calendar_connections: List[CalendarConnectionBackup] = []
    integration_connections: List[IntegrationConnectionBackup] = []


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
    warnings: List[str] = []
