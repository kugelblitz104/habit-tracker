from datetime import date, datetime
from typing import overload

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import (
    non_blank_string,
    reject_null,
    validate_hex_color,
)


@overload
def _validate_positive(v: int) -> int: ...
@overload
def _validate_positive(v: None) -> None: ...
def _validate_positive(v: int | None) -> int | None:
    if v is not None and v <= 0:
        raise ValueError("Frequency and range must be positive integers")
    return v


# Habit Schemas
class HabitBase(BaseModel):
    name: str
    question: str
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: str | None = None
    archived: bool = False
    sort_order: int = 0
    category: str | None = None
    # Required: a habit's profile is always explicit. HabitUpdate declares its
    # own optional profile_id (omitted = keep the habit's current profile).
    profile_id: int

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        return validate_hex_color(v)

    @field_validator("frequency", "range")
    @classmethod
    def validate_frequency_and_range(cls, v: int) -> int:
        return _validate_positive(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return non_blank_string(v, "Name")


class HabitCreate(HabitBase):
    pass


class HabitRead(_StampedRead, HabitBase):
    completed_today: bool = False
    skipped_today: bool = False
    # Server-assigned URL slug derived from `name` (see core/slugs.py). Read-only
    # by design: absent from HabitCreate/HabitUpdate so a client can never set or
    # clear it. Declared last so adding it appends to the OpenAPI properties
    # rather than reordering them.
    slug: str


class HabitUpdate(BaseModel):
    name: str | None = None
    question: str | None = None
    color: str | None = None
    frequency: int | None = None
    range: int | None = None
    reminder: bool | None = None
    notes: str | None = None
    archived: bool | None = None
    sort_order: int | None = None
    category: str | None = None
    profile_id: int | None = None
    updated_date: datetime = Field(default_factory=datetime.now)

    @field_validator(
        "profile_id",
        "name",
        "question",
        "color",
        "frequency",
        "range",
        "reminder",
        "archived",
        "sort_order",
    )
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        # (notes and category ARE nullable, so an explicit null clears them.)
        return reject_null(v, info)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return non_blank_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)

    @field_validator("frequency", "range")
    @classmethod
    def validate_frequency_and_range(cls, v: int | None) -> int | None:
        return _validate_positive(v)


class HabitList(BaseModel):
    habits: list[HabitRead] = []
    total: int
    limit: int
    offset: int


class HabitStreak(BaseModel):
    """A single unbroken run of days that count toward a habit's streak.

    A day counts when it has an explicit completion or skip, or when it is
    auto-skipped (the frequency goal was already met within the range window).
    """

    start_date: date
    end_date: date
    length: int


class HabitKPIs(BaseModel):
    """Computed statistics for a single habit.

    All values are derived from the habit's trackers on the fly - nothing here
    is persisted. Mirrors the frontend's client-side computation so the two
    agree.
    """

    total_completions: int = Field(
        ..., description="Count of trackers with status COMPLETED"
    )
    current_streak: int = Field(
        ..., description="Length of the ongoing streak (0 unless it includes today)"
    )
    longest_streak: int = Field(
        ..., description="Length of the longest streak on record"
    )
    longest_streak_end_date: date | None = Field(
        None,
        description="End date of the longest streak (for a 'days · Mon' sublabel); "
        "None if there is no streak",
    )
    thirty_day_completion_rate: float = Field(
        ...,
        description="Completion rate (0.0-1.0) over the trailing 30 days",
    )
    overall_completion_rate: float = Field(
        ...,
        description="Completion rate (0.0-1.0) since the habit's effective start date",
    )
    last_completed_date: date | None = Field(
        None, description="Date of the most recent completion, or None"
    )
    weekday_completion_rates: list[float] = Field(
        ...,
        description="Length-7 list of completion rates (0.0-1.0), one per weekday, "
        "indexed by Python date.weekday(): index 0 = Monday ... 6 = Sunday. "
        "The frontend reorders these for display.",
    )
