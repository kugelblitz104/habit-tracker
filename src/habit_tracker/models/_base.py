"""Shared base classes for `*Read` models.

Pydantic v2 collects fields in reverse-MRO order, so field order here is
load-bearing: `class XRead(_StampedRead, XBase)` yields `XBase`'s fields
first and the id/created_date/updated_date triple last - the same order as
declaring them inline. Reversing the base order reorders `properties` in the
generated OpenAPI schema.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class _FromORM(BaseModel):
    """Base that reads straight off SQLAlchemy ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


class _StampedRead(_FromORM):
    """`_FromORM` plus the common `id, created_date, updated_date` tail.

    Only apply to a `*Read` model whose fields end in exactly this triple, in
    this order, with nothing interleaved among them.
    """

    id: int
    created_date: datetime
    updated_date: Optional[datetime] = None
