from datetime import date, datetime, time
from typing import List, Optional, overload

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
def _validate_priority(v: Optional[int]) -> Optional[int]:
    return validate_membership(v, _PRIORITY_VALUES, "Priority must be between 0 and 3")


@overload
def _validate_status(v: int) -> int: ...
@overload
def _validate_status(v: None) -> None: ...
def _validate_status(v: Optional[int]) -> Optional[int]:
    return validate_membership(
        v, [s.value for s in TaskStatus], "Status must be a valid TaskStatus value"
    )


# Task Schemas
class TaskBase(BaseModel):
    profile_id: int
    title: str
    notes: Optional[str] = None
    priority: int = 0
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    scheduled_date: Optional[date] = None
    scheduled_time: Optional[time] = None
    status: int = TaskStatus.OPEN
    block_reason: Optional[str] = None
    source: Optional[str] = None
    external_ref: Optional[str] = None
    external_url: Optional[str] = None
    estimated_effort: Optional[int] = None
    project_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: int = 0

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return non_blank_string(v, "Title")

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: Optional[int]) -> Optional[int]:
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
    closed_date: Optional[datetime] = None
    created_date: datetime
    updated_date: Optional[datetime] = None
    band: str = TaskBand.WHENEVER
    # Computed, never stored: how many subtasks this task has, and how many
    # of them are DONE (cancelled subtasks count toward subtask_count only)
    subtask_count: int = 0
    subtask_done_count: int = 0


class TaskUpdate(BaseModel):
    profile_id: Optional[int] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[int] = None
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    scheduled_date: Optional[date] = None
    scheduled_time: Optional[time] = None
    status: Optional[int] = None
    block_reason: Optional[str] = None
    source: Optional[str] = None
    external_ref: Optional[str] = None
    external_url: Optional[str] = None
    estimated_effort: Optional[int] = None
    project_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None

    @field_validator("profile_id", "title", "priority", "status")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        return non_blank_string(v, "Title")

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[int]) -> Optional[int]:
        return _validate_priority(v)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[int]) -> Optional[int]:
        return _validate_status(v)

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: Optional[int]) -> Optional[int]:
        return non_negative_int(v, "Estimated effort")


class TaskList(BaseModel):
    tasks: List[TaskRead] = []
    total: int
    limit: int
    offset: int
