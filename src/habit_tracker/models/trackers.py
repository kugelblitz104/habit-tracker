from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# Tracker Schemas
class TrackerBase(BaseModel):
    habit_id: int
    dated: date = date.today()
    completed: bool = True
    skipped: bool = False
    note: Optional[str] = None


class TrackerCreate(TrackerBase):
    pass


class TrackerRead(TrackerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None


class TrackerUpdate(BaseModel):
    dated: Optional[date] = None
    completed: Optional[bool] = None
    skipped: Optional[bool] = None
    note: Optional[str] = None
    updated_date: datetime = datetime.now()


class TrackerList(BaseModel):
    trackers: List[TrackerRead] = []
