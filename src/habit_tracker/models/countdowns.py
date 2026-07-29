from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import CountdownRepeat
from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import (
    non_blank_string,
    reject_null,
    validate_hex_color,
    validate_membership,
)

# "monthly_weekday" recurs on the Nth weekday of the month (e.g. 3rd Monday),
# with N + weekday derived from the anchor target_date; the rest are calendar
# rules (same day-of-month / same month+day).
REPEAT_VALUES = tuple(r.value for r in CountdownRepeat)


def _validate_repeat(v: Optional[str]) -> Optional[str]:
    return validate_membership(v, REPEAT_VALUES, f"repeat must be one of {REPEAT_VALUES}")


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
        return non_blank_string(v, "Title")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return validate_hex_color(v)

    @field_validator("repeat")
    @classmethod
    def validate_repeat(cls, v: str) -> str:
        return _validate_repeat(v) or "none"


class CountdownCreate(CountdownBase):
    pass


class CountdownRead(_StampedRead, CountdownBase):
    pass


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
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        return non_blank_string(v, "Title")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return validate_hex_color(v)

    @field_validator("repeat")
    @classmethod
    def validate_repeat(cls, v: Optional[str]) -> Optional[str]:
        return _validate_repeat(v)


class CountdownList(BaseModel):
    countdowns: List[CountdownRead] = []
    total: int
    limit: int
    offset: int
