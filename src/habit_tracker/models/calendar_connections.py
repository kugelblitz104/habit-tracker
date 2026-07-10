import re
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


# Calendar Connection Schemas
class CalendarConnectionBase(BaseModel):
    name: str
    color: str
    url: str
    provider: Optional[str] = None
    enabled: bool = True

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

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("URL cannot be empty or whitespace")
        v = normalize_ics_url(v)
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http://, https://, or webcal://")
        return v


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


class CalendarConnectionRead(CalendarConnectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    created_date: datetime
    updated_date: Optional[datetime] = None
    last_fetched_at: Optional[datetime] = None
    last_error: Optional[str] = None


class CalendarConnectionUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    url: Optional[str] = None
    provider: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("name", "color", "url", "enabled")
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

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("URL cannot be empty or whitespace")
            v = normalize_ics_url(v)
            if not v.startswith(("http://", "https://")):
                raise ValueError("URL must start with http://, https://, or webcal://")
        return v


class CalendarConnectionList(BaseModel):
    calendar_connections: List[CalendarConnectionRead] = []
    total: int
    limit: int
    offset: int


class CalendarEventRead(BaseModel):
    connection_id: int
    calendar_name: str
    color: str
    title: str
    location: Optional[str] = None
    all_day: bool
    start: datetime
    end: Optional[datetime] = None


class CalendarEventList(BaseModel):
    events: List[CalendarEventRead] = []
    date: date
    errors: List[str] = []
