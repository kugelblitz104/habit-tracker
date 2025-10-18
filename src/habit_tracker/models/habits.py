from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# Habit Schemas
class HabitBase(BaseModel):
    user_id: int
    name: str
    question: str
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: Optional[str] = None


class HabitCreate(HabitBase):
    pass


class HabitRead(HabitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None


class HabitKPIs(BaseModel):
    id: int
    current_streak: int | None
    longest_streak: int | None
    total_completions: int
    thirty_day_completion_rate: float
    overall_completion_rate: float
    last_completed_date: Optional[datetime] = None


class HabitUpdate(BaseModel):
    name: Optional[str] = None
    question: Optional[str] = None
    color: Optional[str] = None
    frequency: Optional[int] = None
    reminder: Optional[bool] = None
    notes: Optional[str] = None
    updated_date: datetime = datetime.now()


class HabitList(BaseModel):
    habits: List[HabitRead] = []
