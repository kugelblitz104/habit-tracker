"""Pydantic request/response models only.

This barrel must never re-export SQLAlchemy ORM classes (those live in
`habit_tracker.schemas.db_models`) or the shared enums (those live in
`habit_tracker.constants`). Conflating the two layers is exactly what
CLAUDE.md warns against: `from habit_tracker.models import Task` must always
hand back the Pydantic `Task`-shaped model, never the ORM table.
"""

from habit_tracker.models.backup import (
    CalendarConnectionBackup,
    CountdownBackup,
    HabitBackup,
    ImportSummary,
    IntegrationConnectionBackup,
    ProfileBackup,
    ProfileSettings,
    ProjectBackup,
    TaskBackup,
    TimeEntryBackup,
    TrackerBackup,
)
from habit_tracker.models.calendar_connections import (
    CalendarConnectionCreate,
    CalendarConnectionList,
    CalendarConnectionRead,
    CalendarConnectionUpdate,
    CalendarEventList,
    CalendarEventRead,
    normalize_ics_url,
)
from habit_tracker.models.countdowns import (
    CountdownCreate,
    CountdownList,
    CountdownRead,
    CountdownUpdate,
)
from habit_tracker.models.habits import (
    HabitCreate,
    HabitKPIs,
    HabitList,
    HabitRead,
    HabitStreak,
    HabitUpdate,
)
from habit_tracker.models.imports import (
    ExportResult,
    ImportedHabitSummary,
    ImportResult,
)
from habit_tracker.models.integrations import (
    IntegrationConnectionCreate,
    IntegrationConnectionList,
    IntegrationConnectionRead,
    IntegrationConnectionUpdate,
    IntegrationSyncResult,
    PublishRequest,
    PublishResult,
)
from habit_tracker.models.profiles import (
    ProfileCreate,
    ProfileList,
    ProfileRead,
    ProfileUpdate,
)
from habit_tracker.models.projects import (
    ProjectCreate,
    ProjectList,
    ProjectRead,
    ProjectUpdate,
)
from habit_tracker.models.tasks import (
    TaskCreate,
    TaskList,
    TaskRead,
    TaskUpdate,
)
from habit_tracker.models.time_entries import (
    ProjectTimeSummary,
    TaskTimeSummary,
    TimeEntryCreate,
    TimeEntryList,
    TimeEntryRead,
    TimeEntrySummary,
    TimeEntryUpdate,
)
from habit_tracker.models.trackers import (
    TrackerCreate,
    TrackerList,
    TrackerLite,
    TrackerLiteList,
    TrackerRead,
    TrackerUpdate,
)
from habit_tracker.models.users import (
    ForgotPasswordRequest,
    MessageResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserList,
    UserRead,
    UserUpdate,
)

__all__ = [
    "CalendarConnectionBackup",
    "CalendarConnectionCreate",
    "CalendarConnectionList",
    "CalendarConnectionRead",
    "CalendarConnectionUpdate",
    "CalendarEventList",
    "CalendarEventRead",
    "CountdownBackup",
    # Pydantic Schemas
    "CountdownCreate",
    "CountdownList",
    "CountdownRead",
    "CountdownUpdate",
    "ExportResult",
    "ForgotPasswordRequest",
    "HabitBackup",
    "HabitCreate",
    "HabitKPIs",
    "HabitList",
    "HabitRead",
    "HabitStreak",
    "HabitUpdate",
    "ImportResult",
    "ImportSummary",
    "ImportedHabitSummary",
    "IntegrationConnectionBackup",
    "IntegrationConnectionCreate",
    "IntegrationConnectionList",
    "IntegrationConnectionRead",
    "IntegrationConnectionUpdate",
    "IntegrationSyncResult",
    "MessageResponse",
    "ProfileBackup",
    "ProfileCreate",
    "ProfileList",
    "ProfileRead",
    "ProfileSettings",
    "ProfileUpdate",
    "ProjectBackup",
    "ProjectCreate",
    "ProjectList",
    "ProjectRead",
    "ProjectTimeSummary",
    "ProjectUpdate",
    "PublishRequest",
    "PublishResult",
    "RefreshTokenRequest",
    "ResetPasswordRequest",
    "TaskBackup",
    "TaskCreate",
    "TaskList",
    "TaskRead",
    "TaskTimeSummary",
    "TaskUpdate",
    "TimeEntryBackup",
    "TimeEntryCreate",
    "TimeEntryList",
    "TimeEntryRead",
    "TimeEntrySummary",
    "TimeEntryUpdate",
    "Token",
    "TrackerBackup",
    "TrackerCreate",
    "TrackerList",
    "TrackerLite",
    "TrackerLiteList",
    "TrackerRead",
    "TrackerUpdate",
    "UserCreate",
    "UserList",
    "UserRead",
    "UserUpdate",
    "normalize_ics_url",
]
