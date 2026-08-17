from datetime import date, datetime
from typing import overload

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from habit_tracker.constants import TrackerStatus
from habit_tracker.models._base import _FromORM, _StampedRead
from habit_tracker.models._validators import reject_null, validate_membership

_STATUS_VALUES = [s.value for s in TrackerStatus]


@overload
def _validate_status(v: int) -> int: ...
@overload
def _validate_status(v: None) -> None: ...
def _validate_status(v: int | None) -> int | None:
    return validate_membership(
        v, _STATUS_VALUES, "Status must be a valid TrackerStatus value"
    )


# Tracker Schemas
class TrackerBase(BaseModel):
    habit_id: int
    dated: date = Field(default_factory=date.today)
    status: int = Field()
    note: str | None = None


class TrackerCreate(TrackerBase):
    pass


class TrackerRead(_StampedRead, TrackerBase):
    pass


class TrackerLite(_FromORM):
    """Lightweight tracker schema for efficient data fetching."""

    id: int
    dated: date
    status: int  # 0=not completed, 1=skipped, 2=completed
    has_note: bool


class TrackerUpdate(BaseModel):
    dated: date | None = None
    status: int | None = None  # 0=not completed, 1=skipped, 2=completed
    note: str | None = None
    updated_date: datetime = Field(default_factory=datetime.now)

    @field_validator("dated", "status")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        # (note IS nullable, so an explicit null clears it. habit_id isn't
        # settable here at all - trackers don't move between habits.)
        return reject_null(v, info)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: int | None) -> int | None:
        return _validate_status(v)


class TrackerList(BaseModel):
    trackers: list[TrackerRead] = []
    total: int
    limit: int
    offset: int


class TrackerLiteList(BaseModel):
    """Lightweight tracker list for efficient data fetching with date-based pagination."""

    trackers: list[TrackerLite] = []
    total: int
    end_date: date
    days: int
    has_previous: bool = False  # Indicates if there are older trackers
    auto_skipped_dates: list[date] = Field(
        default_factory=list,
    )
    limit: int = 1000
    offset: int = 0
