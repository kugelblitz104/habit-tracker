from datetime import date, datetime
from typing import overload

from pydantic import BaseModel, ValidationInfo, field_validator

from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import (
    non_blank_string,
    reject_null,
    validate_hex_color,
)


@overload
def _validate_calendar_url(v: str) -> str: ...
@overload
def _validate_calendar_url(v: None) -> None: ...
def _validate_calendar_url(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.strip():
        raise ValueError("URL cannot be empty or whitespace")
    v = normalize_ics_url(v)
    if not v.startswith(("http://", "https://")):
        raise ValueError("URL must start with http://, https://, or webcal://")
    return v


# Calendar Connection Schemas
class CalendarConnectionBase(BaseModel):
    name: str
    color: str
    url: str
    provider: str | None = None
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return non_blank_string(v, "Name")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        return validate_hex_color(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return _validate_calendar_url(v)


def normalize_ics_url(url: str) -> str:
    """Normalize calendar subscription URLs.

    Providers like Proton and Apple surface subscription links with the
    `webcal://` pseudo-scheme; it's plain HTTPS underneath, so rewrite it
    rather than rejecting the paste.
    """
    stripped = url.strip()
    if stripped.lower().startswith("webcal://"):
        return "https://" + stripped[len("webcal://") :]
    return stripped


class CalendarConnectionCreate(CalendarConnectionBase):
    profile_id: int


class CalendarConnectionRead(CalendarConnectionBase, _FromORM):
    id: int
    profile_id: int
    created_date: datetime
    updated_date: datetime | None = None
    last_fetched_at: datetime | None = None
    last_error: str | None = None


class CalendarConnectionUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    url: str | None = None
    provider: str | None = None
    enabled: bool | None = None

    @field_validator("name", "color", "url", "enabled")
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

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        return _validate_calendar_url(v)


class CalendarConnectionList(BaseModel):
    calendar_connections: list[CalendarConnectionRead] = []
    total: int
    limit: int
    offset: int


class CalendarEventRead(BaseModel):
    connection_id: int
    calendar_name: str
    color: str
    title: str
    location: str | None = None
    all_day: bool
    event_date: date
    start: datetime
    end: datetime | None = None


class CalendarEventList(BaseModel):
    events: list[CalendarEventRead] = []
    date: date
    errors: list[str] = []
