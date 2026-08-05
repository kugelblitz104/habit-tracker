from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import (
    reject_null,
    trimmed_string,
    validate_hex_color,
)


class CountdownCategoryBase(BaseModel):
    profile_id: int
    name: str
    # Nullable: a category created by naming one on a countdown starts colourless.
    color: str | None = None

    # Trimmed, not merely non-blank: services/countdown_categories.py matches a
    # countdown's category text against the record by its trimmed name, so an
    # untrimmed name here would be a group no countdown can ever match.
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return trimmed_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)


class CountdownCategoryCreate(CountdownCategoryBase):
    pass


class CountdownCategoryRead(_StampedRead, CountdownCategoryBase):
    pass


class CountdownCategoryUpdate(BaseModel):
    name: str | None = None
    color: str | None = None

    # `color` is deliberately absent from reject_null: the column is nullable,
    # so an explicit null clears the colour rather than being invalid.
    @field_validator("name")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return trimmed_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        return validate_hex_color(v)


class CountdownCategoryList(BaseModel):
    categories: list[CountdownCategoryRead] = []
    total: int
    limit: int
    offset: int
