import re
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Habit Schemas
class HabitBase(BaseModel):
    name: str
    question: str
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: Optional[str] = None
    archived: bool = False
    sort_order: int = 0
    category: Optional[str] = None
    # Optional for back-compat - routers resolve the user's default profile
    profile_id: Optional[int] = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Color must be a valid hex code, e.g., #FFF or #FFFFFF")
        return v

    @field_validator("frequency", "range")
    @classmethod
    def validate_frequency_and_range(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Frequency and range must be positive integers")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v


class HabitCreate(HabitBase):
    pass


class HabitRead(HabitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None
    completed_today: bool = False
    skipped_today: bool = False


class HabitUpdate(BaseModel):
    name: Optional[str] = None
    question: Optional[str] = None
    color: Optional[str] = None
    frequency: Optional[int] = None
    range: Optional[int] = None
    reminder: Optional[bool] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None
    sort_order: Optional[int] = None
    category: Optional[str] = None
    profile_id: Optional[int] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class HabitList(BaseModel):
    habits: List[HabitRead] = []
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
    longest_streak_end_date: Optional[date] = Field(
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
    last_completed_date: Optional[date] = Field(
        None, description="Date of the most recent completion, or None"
    )
    weekday_completion_rates: List[float] = Field(
        ...,
        description="Length-7 list of completion rates (0.0-1.0), one per weekday, "
        "indexed by Python date.weekday(): index 0 = Monday ... 6 = Sunday. "
        "The frontend reorders these for display.",
    )


loopHabitColors = [
    "#D32F2F",  #  0 red
    "#E64A19",  #  1 deep orange
    "#F57C00",  #  2 orange
    "#FF8F00",  #  3 amber
    "#F9A825",  #  4 yellow
    "#AFB42B",  #  5 lime
    "#7CB342",  #  6 light green
    "#388E3C",  #  7 green
    "#00897B",  #  8 teal
    "#00ACC1",  #  9 cyan
    "#039BE5",  # 10 light blue
    "#1976D2",  # 11 blue
    "#303F9F",  # 12 indigo
    "#5E35B1",  # 13 deep purple
    "#8E24AA",  # 14 purple
    "#D81B60",  # 15 pink
    "#5D4037",  # 16 brown
    "#303030",  # 17 dark grey
    "#757575",  # 18 grey
    "#aaaaaa",  # 19 light grey
]
