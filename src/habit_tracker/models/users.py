from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# User Schemas
class UserBase(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: EmailStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Username cannot be empty or whitespace")
        return v


class UserCreate(UserBase):
    plaintext_password: str


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    plaintext_password: Optional[str] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class UserList(BaseModel):
    users: List[UserRead] = []
    total: int
    limit: int
    offset: int


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
