from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import (
    non_blank_string,
    reject_null,
    validate_hex_color,
)


# Project Schemas
class ProjectBase(BaseModel):
    profile_id: int
    name: str
    color: str
    notes: str | None = None
    archived: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return non_blank_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        return validate_hex_color(v)


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(_StampedRead, ProjectBase):
    open_count: int = 0
    done_count: int = 0


class ProjectUpdate(BaseModel):
    profile_id: int | None = None
    name: str | None = None
    color: str | None = None
    notes: str | None = None
    archived: bool | None = None

    @field_validator("profile_id", "name", "color", "archived")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return non_blank_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)


class ProjectList(BaseModel):
    projects: list[ProjectRead] = []
    total: int
    limit: int
    offset: int
