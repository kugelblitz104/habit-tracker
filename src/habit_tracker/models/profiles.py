from typing import List, Optional, overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.constants import DefaultLanding
from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import (
    min_value_int,
    non_blank_string,
    reject_null,
    validate_hex_color,
    validate_membership,
)

_DEFAULT_LANDING_VALUES = tuple(d.value for d in DefaultLanding)


@overload
def _validate_pomodoro(v: int) -> int: ...
@overload
def _validate_pomodoro(v: None) -> None: ...
def _validate_pomodoro(v: Optional[int]) -> Optional[int]:
    return min_value_int(v, 1, "Pomodoro settings")


@overload
def _validate_default_landing(v: str) -> str: ...
@overload
def _validate_default_landing(v: None) -> None: ...
def _validate_default_landing(v: Optional[str]) -> Optional[str]:
    return validate_membership(
        v, _DEFAULT_LANDING_VALUES, "Default landing must be 'today' or 'habits'"
    )


# Profile Schemas
class ProfileBase(BaseModel):
    name: str
    color_start: str = "#e0763f"
    color_end: str = "#c14e6a"
    habits_enabled: bool = True
    countdowns_enabled: bool = True
    insights_enabled: bool = True
    calendar_enabled: bool = True
    publish_to_azure: bool = False
    default_landing: str = "today"
    week_start_monday: bool = True
    use_habit_color_accent: bool = False
    show_estimated_effort: bool = False
    pomodoro_work_minutes: int = 25
    pomodoro_break_minutes: int = 5
    pomodoro_long_break_minutes: int = 15
    pomodoro_cycles: int = 4

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return non_blank_string(v, "Name")

    @field_validator(
        "pomodoro_work_minutes",
        "pomodoro_break_minutes",
        "pomodoro_long_break_minutes",
        "pomodoro_cycles",
    )
    @classmethod
    def validate_pomodoro(cls, v: int) -> int:
        return _validate_pomodoro(v)

    @field_validator("color_start", "color_end")
    @classmethod
    def validate_color(cls, v: str) -> str:
        return validate_hex_color(v)

    @field_validator("default_landing")
    @classmethod
    def validate_default_landing(cls, v: str) -> str:
        return _validate_default_landing(v)


class ProfileCreate(ProfileBase):
    pass


class ProfileRead(_StampedRead, ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    color_start: Optional[str] = None
    color_end: Optional[str] = None
    habits_enabled: Optional[bool] = None
    countdowns_enabled: Optional[bool] = None
    insights_enabled: Optional[bool] = None
    calendar_enabled: Optional[bool] = None
    publish_to_azure: Optional[bool] = None
    default_landing: Optional[str] = None
    week_start_monday: Optional[bool] = None
    use_habit_color_accent: Optional[bool] = None
    show_estimated_effort: Optional[bool] = None
    pomodoro_work_minutes: Optional[int] = None
    pomodoro_break_minutes: Optional[int] = None
    pomodoro_long_break_minutes: Optional[int] = None
    pomodoro_cycles: Optional[int] = None

    @field_validator(
        "name",
        "color_start",
        "color_end",
        "habits_enabled",
        "countdowns_enabled",
        "insights_enabled",
        "calendar_enabled",
        "publish_to_azure",
        "default_landing",
        "week_start_monday",
        "use_habit_color_accent",
        "show_estimated_effort",
        "pomodoro_work_minutes",
        "pomodoro_break_minutes",
        "pomodoro_long_break_minutes",
        "pomodoro_cycles",
    )
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator(
        "pomodoro_work_minutes",
        "pomodoro_break_minutes",
        "pomodoro_long_break_minutes",
        "pomodoro_cycles",
    )
    @classmethod
    def validate_pomodoro(cls, v: Optional[int]) -> Optional[int]:
        return _validate_pomodoro(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        return non_blank_string(v, "Name")

    @field_validator("color_start", "color_end")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return validate_hex_color(v)

    @field_validator("default_landing")
    @classmethod
    def validate_default_landing(cls, v: Optional[str]) -> Optional[str]:
        return _validate_default_landing(v)


class ProfileList(BaseModel):
    profiles: List[ProfileRead] = []
    total: int
    limit: int
    offset: int
