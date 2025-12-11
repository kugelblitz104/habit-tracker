from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# Tracker Schemas
class TrackerBase(BaseModel):
    habit_id: int
    dated: date = Field(default_factory=date.today)
    completed: bool = True
    skipped: bool = False
    note: Optional[str] = None


class TrackerCreate(TrackerBase):
    pass


class TrackerRead(TrackerBase):
    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TrackerUpdate(BaseModel):
    dated: Optional[date] = None
    completed: Optional[bool] = None
    skipped: Optional[bool] = None
    note: Optional[str] = None
    updated_date: datetime = Field(default_factory=datetime.now)


class TrackerList(BaseModel):
    trackers: List[TrackerRead] = []
    total: int
    limit: int
    offset: int


class Streak(BaseModel):
    start_date: date
    end_date: date

    @classmethod
    def from_date(cls, start: date) -> "Streak":
        return cls(start_date=start, end_date=start)

    def length(self) -> int:
        return (self.end_date - self.start_date).days + 1
