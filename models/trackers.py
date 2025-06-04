from sqlmodel import Field, Relationship, SQLModel
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .habits import Habit

class TrackerBase(SQLModel):
    habit_id: int
    timestamp: datetime = Field(default_factory=datetime.now)
    completed: bool = True
    skipped: bool = False

class Tracker(TrackerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    habit_id: int = Field(foreign_key="habit.id")
    habit: Optional["Habit"] = Relationship(back_populates="trackers")

class TrackerCreate(TrackerBase):
    pass

class TrackerRead(TrackerBase):
    id: int

class TrackerUpdate(SQLModel):
    completed: Optional[bool] = None
    skipped: Optional[bool] = None

class TrackerDelete(SQLModel):
    id: int

class TrackerList(SQLModel):
    trackers: List[TrackerRead] = Field(default_factory=list)

Tracker.model_rebuild()
TrackerRead.model_rebuild()
TrackerList.model_rebuild()