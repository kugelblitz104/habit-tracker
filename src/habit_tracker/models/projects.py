import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


# Project Schemas
class ProjectBase(BaseModel):
    profile_id: int
    name: str
    color: str
    notes: Optional[str] = None
    archived: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
        return v


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None
    open_count: int = 0
    done_count: int = 0


class ProjectUpdate(BaseModel):
    profile_id: Optional[int] = None
    name: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None

    @field_validator("profile_id", "name", "color", "archived")
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

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Color must be a valid hex code, e.g., #FFFFFF")
        return v


class ProjectList(BaseModel):
    projects: List[ProjectRead] = []
    total: int
    limit: int
    offset: int
