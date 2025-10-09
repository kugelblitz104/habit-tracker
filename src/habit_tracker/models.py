from datetime import date, datetime
from typing import List, Optional

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel


class UserBase(SQLModel):
    username: str
    first_name: str
    last_name: str
    email: EmailStr


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    password_hash: str
    habits: List["Habit"] = Relationship(back_populates="user", cascade_delete=True)
    created_date: datetime = Field(default_factory=datetime.now)
    updated_date: Optional[datetime] = None


class UserCreate(UserBase):
    password_hash: str


class UserRead(UserBase):
    id: int
    habits: List["Habit"] = Field(default_factory=list)
    created_date: datetime
    updated_date: Optional[datetime] = None


class UserUpdate(SQLModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password_hash: Optional[str] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class UserList(SQLModel):
    users: List[UserRead] = Field(default_factory=list)


class HabitBase(SQLModel):
    user_id: int
    name: str
    question: str
    color: str
    frequency: int
    range: int
    reminder: bool = False
    notes: Optional[str] = None


class Habit(HabitBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="habits")
    trackers: List["Tracker"] = Relationship(
        back_populates="habit", cascade_delete=True
    )
    name: str = Field()
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
    updated_date: datetime = Field(default_factory=datetime.now)


class HabitList(SQLModel):
    habits: List[HabitRead] = Field(default_factory=list)


class TrackerBase(SQLModel):
    habit_id: int
    dated: date = Field(default_factory=datetime.now)
    completed: bool = True
    skipped: bool = False
    note: Optional[str] = None


class Tracker(TrackerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    habit_id: int = Field(foreign_key="habit.id")
    habit: Optional["Habit"] = Relationship(back_populates="trackers")
    created_date: datetime = Field(default_factory=datetime.now)
    updated_date: Optional[datetime] = None


class TrackerCreate(TrackerBase):
    pass


class TrackerRead(TrackerBase):
    id: int


class TrackerUpdate(SQLModel):
    dated: Optional[date] = None
    completed: Optional[bool] = None
    skipped: Optional[bool] = None
    note: Optional[str] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class TrackerList(SQLModel):
    trackers: List[TrackerRead] = Field(default_factory=list)
