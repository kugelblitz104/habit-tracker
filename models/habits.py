from sqlmodel import Field, Relationship, SQLModel
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .users import User
    from .trackers import Tracker

class HabitBase(SQLModel):
    user_id: int
    name: str
    question: str
    color: str
    frequency: str
    reminder: bool = False
    notes: Optional[str] = None

class Habit(HabitBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="habits")
    trackers: List["Tracker"] = Relationship(back_populates="habit")
    name: str = Field()
    reminder: bool = False
    notes: Optional[str] = None
    created_date: datetime = Field(default_factory=datetime.now)
    updated_date: Optional[datetime] = None

class HabitCreate(HabitBase):
    pass

class HabitRead(HabitBase):
    id: int
    trackers: List["Tracker"] = Field(default_factory=list)
    created_date: datetime
    updated_date: Optional[datetime] = None

class HabitUpdate(SQLModel):
    name: Optional[str] = None
    question: Optional[str] = None
    color: Optional[str] = None
    frequency: Optional[str] = None
    reminder: Optional[bool] = None
    notes: Optional[str] = None

class HabitDelete(SQLModel):
    id: int

class HabitList(SQLModel):
    habits: List[HabitRead] = Field(default_factory=list)

Habit.model_rebuild()
HabitRead.model_rebuild()
HabitList.model_rebuild()
