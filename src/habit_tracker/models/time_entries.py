from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from habit_tracker.constants import TimeEntryKind


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
        if v not in [k.value for k in TimeEntryKind]:
            raise ValueError("Kind must be a valid TimeEntryKind value")
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: Optional[str]) -> Optional[str]:
        # Normalize blank labels to null so autofill never suggests empties.
        if v is not None and not v.strip():
            return None
        return v


class TimeEntryCreate(TimeEntryBase):
    # Both timestamps optional. Omit them to START a running timer at "now".
    # Provide ended_at (and optionally started_at) to LOG a completed entry -
    # duration_seconds is always computed server-side, never client-supplied.
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class TimeEntryRead(TimeEntryBase):
    model_config = ConfigDict(from_attributes=True)

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
    def reject_null(cls, v: object, info: ValidationInfo) -> object:
        # These columns are NOT NULL in the database; omitting a field means
        # "leave unchanged", but an explicit null is always invalid. (task_id,
        # project_id, label, note and ended_at ARE nullable, so an explicit
        # null clears them - nulling ended_at reopens the entry as running.)
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in [k.value for k in TimeEntryKind]:
            raise ValueError("Kind must be a valid TimeEntryKind value")
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            return None
        return v


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
