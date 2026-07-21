import re
from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


# "monthly_weekday" recurs on the Nth weekday of the month (e.g. 3rd Monday),
# with N + weekday derived from the anchor target_date; the rest are calendar
# rules (same day-of-month / same month+day).
REPEAT_VALUES = ("none", "weekly", "monthly", "monthly_weekday", "yearly")


def _validate_hex_color(v: Optional[str]) -> Optional[str]:
    if v is not None and not re.match(r"^#[0-9A-Fa-f]{6}$", v):
        raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
    return v


def _validate_repeat(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in REPEAT_VALUES:
        raise ValueError(f"repeat must be one of {REPEAT_VALUES}")
    return v


# Countdown Schemas
class CountdownBase(BaseModel):
    profile_id: int
    title: str
    target_date: date
    target_time: Optional[time] = None
    # Optional link to a task; a countdown can stand alone.
    task_id: Optional[int] = None
    # Free-text grouping label + optional hex accent for the grouped views.
    category: Optional[str] = None
    color: Optional[str] = None
    # Recurrence anchored on target_date; next occurrence is computed client-side.
    repeat: str = "none"
    # Opt-in Nth-occurrence display for recurring countdowns (e.g. 26th birthday).
    show_occurrence: bool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty or whitespace")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)

    @field_validator("repeat")
    @classmethod
    def validate_repeat(cls, v: str) -> str:
        return _validate_repeat(v) or "none"


class CountdownCreate(CountdownBase):
    pass


class CountdownRead(CountdownBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None


class CountdownUpdate(BaseModel):
    profile_id: Optional[int] = None
    title: Optional[str] = None
    target_date: Optional[date] = None
    target_time: Optional[time] = None
    task_id: Optional[int] = None
    category: Optional[str] = None
    color: Optional[str] = None
    repeat: Optional[str] = None
    show_occurrence: Optional[bool] = None

    @field_validator("profile_id", "title", "target_date", "repeat", "show_occurrence")
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

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)

    @field_validator("repeat")
    @classmethod
    def validate_repeat(cls, v: Optional[str]) -> Optional[str]:
        return _validate_repeat(v)


class CountdownList(BaseModel):
    countdowns: List[CountdownRead] = []
    total: int
    limit: int
    offset: int
