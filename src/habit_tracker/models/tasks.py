from datetime import date, datetime, time
from typing import overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import (
    IntegrationProvider,
    TaskBand,
    TaskPriority,
    TaskStatus,
)
from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import (
    non_blank_string,
    non_negative_int,
    normalize_external_url,
    reject_null,
    trimmed_or_none,
    validate_membership,
)

_PRIORITY_VALUES = tuple(p.value for p in TaskPriority)
# The provider that produced an external link. NULL is also valid and means the
# link has no integration behind it - a work item pasted in by hand.
_SOURCE_VALUES = {p.value for p in IntegrationProvider}


@overload
def _validate_priority(v: int) -> int: ...
@overload
def _validate_priority(v: None) -> None: ...
def _validate_priority(v: int | None) -> int | None:
    return validate_membership(v, _PRIORITY_VALUES, "Priority must be between 0 and 3")


@overload
def _validate_status(v: int) -> int: ...
@overload
def _validate_status(v: None) -> None: ...
def _validate_status(v: int | None) -> int | None:
    return validate_membership(
        v, [s.value for s in TaskStatus], "Status must be a valid TaskStatus value"
    )


def _validate_source(v: str | None) -> str | None:
    return validate_membership(
        v, _SOURCE_VALUES, f"source must be one of {sorted(_SOURCE_VALUES)} or null"
    )


# Task Schemas
class TaskBase(BaseModel):
    profile_id: int
    title: str
    notes: str | None = None
    priority: int = 0
    due_date: date | None = None
    due_time: time | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    status: int = TaskStatus.OPEN
    block_reason: str | None = None
    source: str | None = None
    external_ref: str | None = None
    external_url: str | None = None
    estimated_effort: int | None = None
    project_id: int | None = None
    parent_id: int | None = None
    sort_order: int = 0

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return non_blank_string(v, "Title")

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: int | None) -> int | None:
        return non_negative_int(v, "Estimated effort")

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        return _validate_priority(v)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: int) -> int:
        return _validate_status(v)

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str | None) -> str | None:
        return _validate_source(v)

    @field_validator("external_ref")
    @classmethod
    def validate_external_ref(cls, v: str | None) -> str | None:
        return trimmed_or_none(v)

    @field_validator("external_url")
    @classmethod
    def validate_external_url(cls, v: str | None) -> str | None:
        return normalize_external_url(v)


class TaskCreate(TaskBase):
    pass


class TaskRead(TaskBase, _FromORM):
    id: int
    closed_date: datetime | None = None
    created_date: datetime
    updated_date: datetime | None = None
    band: str = TaskBand.WHENEVER
    # Computed, never stored: how many subtasks this task has, and how many
    # of them are DONE (cancelled subtasks count toward subtask_count only)
    subtask_count: int = 0
    subtask_done_count: int = 0
    # Server-assigned URL slug (see core/slugs.py). Read-only by design: absent
    # from TaskCreate/TaskUpdate so a client can never set or clear it. Always
    # present, like the title it derives from.
    # Declared last so adding it appends to the OpenAPI properties rather than
    # reordering them.
    slug: str


class TaskUpdate(BaseModel):
    profile_id: int | None = None
    title: str | None = None
    notes: str | None = None
    priority: int | None = None
    due_date: date | None = None
    due_time: time | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    status: int | None = None
    block_reason: str | None = None
    source: str | None = None
    external_ref: str | None = None
    external_url: str | None = None
    estimated_effort: int | None = None
    project_id: int | None = None
    parent_id: int | None = None
    sort_order: int | None = None

    @field_validator("profile_id", "title", "priority", "status")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        return non_blank_string(v, "Title")

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int | None) -> int | None:
        return _validate_priority(v)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: int | None) -> int | None:
        return _validate_status(v)

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: int | None) -> int | None:
        return non_negative_int(v, "Estimated effort")

    # The link triple stays out of `reject_null` above: all three columns are
    # nullable, and sending explicit nulls is how a client unlinks a task.
    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str | None) -> str | None:
        return _validate_source(v)

    @field_validator("external_ref")
    @classmethod
    def validate_external_ref(cls, v: str | None) -> str | None:
        return trimmed_or_none(v)

    @field_validator("external_url")
    @classmethod
    def validate_external_url(cls, v: str | None) -> str | None:
        return normalize_external_url(v)


class TaskList(BaseModel):
    tasks: list[TaskRead] = []
    total: int
    limit: int
    offset: int
