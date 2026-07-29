from datetime import date, datetime, time
from typing import overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import TaskBand, TaskPriority, TaskStatus
from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import (
    non_blank_string,
    non_negative_int,
    reject_null,
    validate_membership,
)

_PRIORITY_VALUES = tuple(p.value for p in TaskPriority)


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


class TaskList(BaseModel):
    tasks: list[TaskRead] = []
    total: int
    limit: int
    offset: int
