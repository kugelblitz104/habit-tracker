from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# Tracker Schemas
class TrackerBase(BaseModel):
    habit_id: int
    dated: date = Field(default_factory=date.today)
    status: int = Field()
    note: Optional[str] = None


class TrackerCreate(TrackerBase):
    pass


class TrackerRead(TrackerBase):
    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TrackerLite(BaseModel):
    """Lightweight tracker schema for efficient data fetching."""

    id: int
    dated: date
    status: int  # 0=not completed, 1=skipped, 2=completed
    has_note: bool

    model_config = ConfigDict(from_attributes=True)


class TrackerUpdate(BaseModel):
    dated: Optional[date] = None
    status: Optional[int] = None  # 0=not completed, 1=skipped, 2=completed
    note: Optional[str] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class TrackerList(BaseModel):
    trackers: List[TrackerRead] = []
    total: int
    limit: int
    offset: int


class TrackerLiteList(BaseModel):
    """Lightweight tracker list for efficient data fetching."""

    trackers: List[TrackerLite] = []
    total: int
    limit: int
    offset: int
