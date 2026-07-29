from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import non_blank_string


# User Schemas
class UserBase(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: EmailStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return non_blank_string(v, "Username")


class UserCreate(UserBase):
    plaintext_password: str


class UserRead(_StampedRead, UserBase):
    pass


class UserUpdate(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    plaintext_password: str | None = None
    updated_date: datetime = Field(default_factory=datetime.now)


class UserList(BaseModel):
    users: list[UserRead] = []
    total: int
    limit: int
    offset: int


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class MessageResponse(BaseModel):
    message: str
