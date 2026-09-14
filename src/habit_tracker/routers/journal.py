from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.core.http import bulk_delete_in_profile, integrity_conflict
from habit_tracker.models import (
    JournalEntryCreate,
    JournalEntryList,
    JournalEntryRead,
)
from habit_tracker.schemas.db_models import JournalEntry, User

router = APIRouter(
    prefix="/journal",
    tags=["journal"],
    responses={404: {"description": "Not found"}},
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found"
    )


async def _fetch(
    db: AsyncSession, profile_id: int, entry_date: date
) -> JournalEntry | None:
    return (
        await db.execute(
            select(JournalEntry).filter(
                JournalEntry.profile_id == profile_id,
                JournalEntry.entry_date == entry_date,
            )
        )
    ).scalar_one_or_none()


@router.get("/", summary="List journal entries for a profile")
async def list_journal_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose entries to list"),
    from_date: date | None = Query(
        default=None, description="Only entries on or after this day"
    ),
    to_date: date | None = Query(
        default=None, description="Only entries on or before this day"
    ),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JournalEntryList:
    """List a profile's journal entries, newest day first.

    - **profile_id**: The profile whose entries to list (required)
    - **from_date**: Only entries on or after this day (optional)
    - **to_date**: Only entries on or before this day (optional)
    - **limit**: Maximum entries to return (1-100, default: 100)
    - **offset**: Number of entries to skip (default: 0)
    """
    await get_owned_profile(db, profile_id, current_user, "journal entry")

    filters = [JournalEntry.profile_id == profile_id]
    if from_date is not None:
        filters.append(JournalEntry.entry_date >= from_date)
    if to_date is not None:
        filters.append(JournalEntry.entry_date <= to_date)

    result = await db.execute(
        select(JournalEntry)
        .filter(*filters)
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id)
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(JournalEntry).filter(*filters)
    )
    total = count_result.scalar() or 0

    return JournalEntryList(
        entries=[JournalEntryRead.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/", summary="Delete every journal entry in a profile")
async def delete_all_journal_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile whose entries to delete"),
) -> JSONResponse:
    """Delete all of a profile's journal entries. This cannot be undone."""
    return await bulk_delete_in_profile(
        db,
        JournalEntry,
        profile_id,
        current_user,
        resource_name="journal entry",
        detail="Deleted {count} journal entries",
    )


@router.get("/{entry_date}", summary="Get the journal entry for one day")
async def read_journal_entry(
    entry_date: date,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile the day belongs to"),
) -> JournalEntryRead:
    """Retrieve one day's journal entry.

    - **entry_date**: The day, YYYY-MM-DD
    - **profile_id**: The profile the day belongs to (required)

    Returns 404 when the day has no entry, which is how a client tells an
    unwritten day from a written one.
    """
    await get_owned_profile(db, profile_id, current_user, "journal entry")

    entry = await _fetch(db, profile_id, entry_date)
    if entry is None:
        raise _not_found()
    return JournalEntryRead.model_validate(entry)


@router.put(
    "/{entry_date}",
    summary="Create or update one day's journal entry",
    responses={
        201: {"description": "A new entry was created for this day"},
        409: {"description": "The entry could not be saved"},
    },
)
async def upsert_journal_entry(
    entry_date: date,
    entry: JournalEntryCreate,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JournalEntryRead:
    """Create or update the journal entry for one day.

    - **entry_date**: The day, YYYY-MM-DD, taken from the path. Any
      `entry_date` in the body is ignored.

    Returns 201 when the day had no entry, 200 when it did.
    """
    profile = await get_owned_profile(
        db, entry.profile_id, current_user, "journal entry"
    )
    owner_id = profile.id

    existing = await _fetch(db, owner_id, entry_date)
    if existing is None:
        row = JournalEntry(
            profile_id=owner_id,
            entry_date=entry_date,
            body=entry.body,
            gratitude=entry.gratitude,
            day_quality=entry.day_quality,
        )
        db.add(row)
        response.status_code = status.HTTP_201_CREATED
    else:
        existing.body = entry.body
        existing.gratitude = entry.gratitude
        existing.day_quality = entry.day_quality
        existing.updated_date = datetime.now()
        row = existing

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # A concurrent request may have inserted this day between our fetch
        # and our commit. Re-fetch: if it exists now, that request won the
        # race and this one becomes the update it should have been.
        row = await _fetch(db, owner_id, entry_date)
        if row is None:
            raise integrity_conflict("Could not save the journal entry") from None
        row.body = entry.body
        row.gratitude = entry.gratitude
        row.day_quality = entry.day_quality
        row.updated_date = datetime.now()
        response.status_code = status.HTTP_200_OK
        await db.commit()

    await db.refresh(row)
    return JournalEntryRead.model_validate(row)


@router.delete(
    "/{entry_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one day's journal entry",
)
async def delete_journal_entry(
    entry_date: date,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    profile_id: int = Query(description="The profile the day belongs to"),
) -> None:
    """Delete one day's journal entry. This cannot be undone."""
    await get_owned_profile(db, profile_id, current_user, "journal entry")

    entry = await _fetch(db, profile_id, entry_date)
    if entry is None:
        raise _not_found()

    await db.delete(entry)
    await db.commit()
