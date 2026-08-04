from datetime import datetime
from typing import overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import TimeEntryKind
from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import (
    blank_to_none,
    reject_null,
    validate_membership,
)

_KIND_VALUES = [k.value for k in TimeEntryKind]


@overload
def _validate_kind(v: int) -> int: ...
@overload
def _validate_kind(v: None) -> None: ...
def _validate_kind(v: int | None) -> int | None:
    return validate_membership(
        v, _KIND_VALUES, "Kind must be a valid TimeEntryKind value"
    )


# Time Entry Schemas
class TimeEntryBase(BaseModel):
    profile_id: int
    task_id: int | None = None
    # Direct project attachment for adhoc (task-less) work. Mutually exclusive
    # with task_id - the router forces this null when a task is attached.
    project_id: int | None = None
    kind: int = TimeEntryKind.STOPWATCH
    label: str | None = None
    note: str | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: int) -> int:
        return _validate_kind(v)

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str | None) -> str | None:
        # Normalize blank labels to null so autofill never suggests empties.
        return blank_to_none(v)


class TimeEntryCreate(TimeEntryBase):
    # Both timestamps optional. Omit them to START a running timer at "now".
    # Provide ended_at (and optionally started_at) to LOG a completed entry -
    # duration_seconds is always computed server-side, never client-supplied.
    started_at: datetime | None = None
    ended_at: datetime | None = None


class TimeEntryRead(TimeEntryBase, _FromORM):
    id: int
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    created_date: datetime
    updated_date: datetime | None = None
    # Computed, never stored: an entry with no ended_at is still running.
    is_running: bool = False
    # Read-only rollup: the project this entry counts toward - its task's
    # project, else its parent task's (so a subtask's time reaches the parent's
    # project), else its own project_id. Never stored, never client-settable.
    resolved_project_id: int | None = None


class TimeEntryUpdate(BaseModel):
    task_id: int | None = None
    project_id: int | None = None
    kind: int | None = None
    label: str | None = None
    note: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @field_validator("kind", "started_at")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        # (task_id, project_id, label, note and ended_at ARE nullable, so an
        # explicit null clears them - nulling ended_at reopens the entry as
        # running.)
        return reject_null(v, info)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: int | None) -> int | None:
        return _validate_kind(v)

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str | None) -> str | None:
        return blank_to_none(v)


class TimeEntryList(BaseModel):
    time_entries: list[TimeEntryRead] = []
    total: int
    limit: int
    offset: int


class TaskTimeSummary(BaseModel):
    # task_id is null for the bucket of untethered (task-less) entries
    task_id: int | None = None
    total_seconds: int
    entry_count: int


class ProjectTimeSummary(BaseModel):
    # A project's total resolves each entry's project as its task's project, or
    # that task's parent's project when the task is a subtask carrying none of
    # its own, or its direct project_id (adhoc). project_id is null for the
    # bucket of entries tied to nothing at all.
    project_id: int | None = None
    total_seconds: int
    entry_count: int


class TimeEntrySummary(BaseModel):
    profile_id: int
    per_task: list[TaskTimeSummary] = []
    per_project: list[ProjectTimeSummary] = []
    total_seconds: int
