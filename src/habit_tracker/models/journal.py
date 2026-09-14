from datetime import date

from pydantic import BaseModel, field_validator

from habit_tracker.constants import DayQuality
from habit_tracker.models._base import _StampedRead
from habit_tracker.models._validators import trimmed_or_none, validate_membership

_DAY_QUALITY_VALUES = tuple(q.value for q in DayQuality)
_QUALITY_MESSAGE = f"Day quality must be one of: {', '.join(_DAY_QUALITY_VALUES)}"


class JournalEntryBase(BaseModel):
    profile_id: int
    body: str | None = None
    # Answers the fixed second prompt. Its own field rather than part of
    # body, so turning the prompt off hides it without losing it.
    gratitude: str | None = None
    # A DayQuality value. Typed str rather than the enum, which would emit an
    # `enum` array into the schema. Nullable on the wire even though the
    # check-in flow requires it: imported history carries none, and a required
    # response field would tighten the generated client.
    day_quality: str | None = None

    @field_validator("body", "gratitude")
    @classmethod
    def validate_prose(cls, v: str | None) -> str | None:
        return trimmed_or_none(v)

    @field_validator("day_quality")
    @classmethod
    def validate_day_quality(cls, v: str | None) -> str | None:
        return validate_membership(v, _DAY_QUALITY_VALUES, _QUALITY_MESSAGE)


class JournalEntryCreate(JournalEntryBase):
    pass


class JournalEntryRead(_StampedRead, JournalEntryBase):
    # The row's identity: a response carries it, and a PUT takes it from the
    # path rather than the body, so it lives here rather than on the base.
    entry_date: date


class JournalEntryList(BaseModel):
    entries: list[JournalEntryRead] = []
    total: int
    limit: int
    offset: int
