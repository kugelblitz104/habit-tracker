import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


# Profile Schemas
class ProfileBase(BaseModel):
    name: str
    color_start: str = "#e0763f"
    color_end: str = "#c14e6a"
    habits_enabled: bool = True
    calendar_enabled: bool = True
    publish_to_azure: bool = False
    default_landing: str = "today"
    week_start_monday: bool = True
    use_habit_color_accent: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v

    @field_validator("color_start", "color_end")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
        return v

    @field_validator("default_landing")
    @classmethod
    def validate_default_landing(cls, v: str) -> str:
        if v not in ("today", "habits"):
            raise ValueError("Default landing must be 'today' or 'habits'")
        return v


class ProfileCreate(ProfileBase):
    pass


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    color_start: Optional[str] = None
    color_end: Optional[str] = None
    habits_enabled: Optional[bool] = None
    calendar_enabled: Optional[bool] = None
    publish_to_azure: Optional[bool] = None
    default_landing: Optional[str] = None
    week_start_monday: Optional[bool] = None
    use_habit_color_accent: Optional[bool] = None

    @field_validator(
        "name",
        "color_start",
        "color_end",
        "habits_enabled",
        "calendar_enabled",
        "publish_to_azure",
        "default_landing",
        "week_start_monday",
        "use_habit_color_accent",
    )
    @classmethod
    def reject_null(cls, v: object, info: ValidationInfo) -> object:
        # These columns are NOT NULL in the database; omitting a field means
        # "leave unchanged", but an explicit null is always invalid
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v

    @field_validator("color_start", "color_end")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
        return v

    @field_validator("default_landing")
    @classmethod
    def validate_default_landing(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("today", "habits"):
            raise ValueError("Default landing must be 'today' or 'habits'")
        return v


class ProfileList(BaseModel):
    profiles: List[ProfileRead] = []
    total: int
    limit: int
    offset: int
