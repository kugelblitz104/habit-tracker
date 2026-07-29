from datetime import datetime
from typing import List, Optional, overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import TimeEntryKind
from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import blank_to_none, reject_null, validate_membership

_KIND_VALUES = [k.value for k in TimeEntryKind]


@overload
def _validate_kind(v: int) -> int: ...
@overload
def _validate_kind(v: None) -> None: ...
def _validate_kind(v: Optional[int]) -> Optional[int]:
    return validate_membership(v, _KIND_VALUES, "Kind must be a valid TimeEntryKind value")


# Time Entry Schemas
class TimeEntryBase(BaseModel):
    profile_id: int
    task_id: Optional[int] = None
    # Direct project attachment for adhoc (task-less) work. Mutually exclusive
    # with task_id - the router forces this null when a task is attached.
    project_id: Optional[int] = None
    kind: int = TimeEntryKind.STOPWATCH
    label: Optional[str] = None
    note: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: int) -> int:
        return _validate_kind(v)

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: Optional[str]) -> Optional[str]:
        # Normalize blank labels to null so autofill never suggests empties.
        return blank_to_none(v)


class TimeEntryCreate(TimeEntryBase):
    # Both timestamps optional. Omit them to START a running timer at "now".
    # Provide ended_at (and optionally started_at) to LOG a completed entry -
    # duration_seconds is always computed server-side, never client-supplied.
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class TimeEntryRead(TimeEntryBase, _FromORM):
    id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_date: datetime
    updated_date: Optional[datetime] = None
    # Computed, never stored: an entry with no ended_at is still running.
    is_running: bool = False


class TimeEntryUpdate(BaseModel):
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    kind: Optional[int] = None
    label: Optional[str] = None
    note: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    @field_validator("kind", "started_at")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        # (task_id, project_id, label, note and ended_at ARE nullable, so an
        # explicit null clears them - nulling ended_at reopens the entry as
        # running.)
        return reject_null(v, info)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: Optional[int]) -> Optional[int]:
        return _validate_kind(v)

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: Optional[str]) -> Optional[str]:
        return blank_to_none(v)


class TimeEntryList(BaseModel):
    time_entries: List[TimeEntryRead] = []
    total: int
    limit: int
    offset: int


class TaskTimeSummary(BaseModel):
    # task_id is null for the bucket of untethered (task-less) entries
    task_id: Optional[int] = None
    total_seconds: int
    entry_count: int


class ProjectTimeSummary(BaseModel):
    # A project's total resolves each entry's project as its task's project
    # (task-attached) or its direct project_id (adhoc). project_id is null for
    # the bucket of entries tied to neither.
    project_id: Optional[int] = None
    total_seconds: int
    entry_count: int


class TimeEntrySummary(BaseModel):
    profile_id: int
    per_task: List[TaskTimeSummary] = []
    per_project: List[ProjectTimeSummary] = []
    total_seconds: int
