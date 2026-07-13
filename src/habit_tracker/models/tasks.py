from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from habit_tracker.constants import TaskBand, TaskStatus


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
    external_ref: Optional[str] = None
    external_url: Optional[str] = None
    estimated_effort: Optional[int] = None
    project_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: int = 0

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty or whitespace")
        return v

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Estimated effort cannot be negative")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        if v not in (0, 1, 2, 3):
            raise ValueError("Priority must be between 0 and 3")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: int) -> int:
        if v not in [status.value for status in TaskStatus]:
            raise ValueError("Status must be a valid TaskStatus value")
        return v


class TaskCreate(TaskBase):
    pass


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

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
    external_ref: Optional[str] = None
    external_url: Optional[str] = None
    estimated_effort: Optional[int] = None
    project_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None

    @field_validator("profile_id", "title", "priority", "status")
    @classmethod
    def reject_null(cls, v: object, info: ValidationInfo) -> object:
        # These columns are NOT NULL in the database; omitting a field means
        # "leave unchanged", but an explicit null is always invalid
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty or whitespace")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in (0, 1, 2, 3):
            raise ValueError("Priority must be between 0 and 3")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in [status.value for status in TaskStatus]:
            raise ValueError("Status must be a valid TaskStatus value")
        return v

    @field_validator("estimated_effort")
    @classmethod
    def validate_estimated_effort(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Estimated effort cannot be negative")
        return v


class TaskList(BaseModel):
    tasks: List[TaskRead] = []
    total: int
    limit: int
    offset: int
