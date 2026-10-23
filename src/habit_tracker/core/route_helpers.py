"""Response/error shapes shared across routers that aren't dependencies.

Everything here is a plain helper called from inside a route function - unlike
`core/dependencies.py`, nothing here is itself a FastAPI `Depends`.
"""

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import get_owned_profile
from habit_tracker.schemas.db_models import User


async def bulk_delete_in_profile(
    db: AsyncSession,
    model: type,
    profile_id: int,
    current_user: User,
    *,
    resource_name: str,
    detail: str,
    where: ColumnElement[bool] | None = None,
) -> JSONResponse:
    """
    Delete every row of `model` scoped to a profile.

    Shared by the six bulk "delete all in a profile" endpoints (countdowns,
    habits, projects, tasks, time entries, trackers). Relies on the DB-level
    `ON DELETE` rules (see `schemas/db_models.py`) for any dependents - never
    deletes related rows by hand.

    Args:
        db: The database session
        model: The ORM model class to delete rows from
        profile_id: The profile to authorize and (by default) scope the delete to
        current_user: The authenticated user
        resource_name: Name of the resource for the 403 error message
        detail: A `{count}`-templated message, e.g. "Deleted {count} tasks"
        where: Overrides the default `model.profile_id == profile_id` clause,
            for models (like Tracker) reached indirectly through another table

    Returns:
        JSONResponse with `detail` (count-formatted) and `deleted`

    Raises:
        HTTPException: 404 if the profile does not exist, 403 if the caller
        is neither the profile's owner nor an admin
    """
    await get_owned_profile(db, profile_id, current_user, resource_name)

    clause = where if where is not None else model.profile_id == profile_id

    count = (
        await db.execute(select(func.count()).select_from(model).where(clause))
    ).scalar() or 0
    await db.execute(delete(model).where(clause))
    await db.commit()
    return JSONResponse(
        content={"detail": detail.format(count=count), "deleted": count}
    )


def integrity_conflict(detail: str) -> HTTPException:
    """
    Build a 409 for an IntegrityError raised on a write.

    Callers keep their own `except IntegrityError: await db.rollback()` (the
    rollback has to stay in the router's session scope) and just
    `raise integrity_conflict(...)`.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def validate_sort_ids(ids: list[int], *, noun: str) -> None:
    """
    Shared preconditions for the `sort_tasks` / `sort_habits` reorder endpoints.

    Raises 400 for an empty list or duplicate ids. The two endpoints
    deliberately diverge on what happens when an id doesn't exist (habits
    probes 403-vs-404, tasks returns a flat 404) - that logic stays in each
    router, not here.

    Raises:
        HTTPException: 400 if `ids` is empty or contains duplicates
    """
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{noun}_ids list cannot be empty",
        )
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate {noun} IDs in request",
        )
