from sqlmodel import Field, Relationship, SQLModel
from pydantic import EmailStr, field_validator
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from typing import ForwardRef

if TYPE_CHECKING:
    from .habits import Habit

class UserBase(SQLModel):
    username: str
    first_name: str
    last_name: str
    email: EmailStr

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    password_hash: str
    habits: List["Habit"] = Relationship(back_populates="user")
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

class UserDelete(SQLModel):
    id: int

class UserList(SQLModel):
    users: List[UserRead] = Field(default_factory=list)

User.model_rebuild()
UserRead.model_rebuild()
UserList.model_rebuild()