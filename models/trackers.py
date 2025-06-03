from sqlmodel import Field, Relationship, SQLModel
from .habits import Habit
from datetime import datetime

class Tracker(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    habit_id: Habit = Relationship(back_populates='trackers')
    timestamp: datetime
    completed: bool = True
    skipped: bool = False