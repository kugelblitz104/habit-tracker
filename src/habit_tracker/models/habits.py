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


class HabitCreate(HabitBase):
    pass


class HabitRead(HabitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None
    completed_today: bool = False
    skipped_today: bool = False


class HabitKPIs(BaseModel):
    id: int
    current_streak: int | None
    longest_streak: int | None
    total_completions: int
    thirty_day_completion_rate: float
    overall_completion_rate: float
    last_completed_date: Optional[date] = None


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
    updated_date: datetime = Field(default_factory=datetime.now)


class HabitList(BaseModel):
    habits: List[HabitRead] = []
    total: int
    limit: int
    offset: int
