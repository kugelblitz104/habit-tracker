"""Full-profile backup: export a profile to a portable JSON document and
import one back as a new profile.

Unlike the per-format helpers (Loop Habit Tracker SQLite, Markdown tasks), this
round-trips *every* entity of a profile in one document, so a user can move a
whole profile between instances — e.g. from the hosted app to an on-prem
server. Import always creates a new profile owned by the caller; it never
merges into or overwrites existing data.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models.backup import ImportSummary, ProfileBackup
from habit_tracker.schemas.db_models import User
from habit_tracker.services.profile_backup import (
    BackupError,
    build_profile_backup,
    load_profile_rows,
    restore_profile_backup,
)

router = APIRouter(
    prefix="/backup",
    tags=["backup"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/profiles/{profile_id}",
    summary="Export a profile and all its data as a portable JSON backup",
)
async def export_profile_backup(
    profile_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProfileBackup:
    """Export the profile's projects, tasks (and subtasks), countdowns, time
    entries, habits, trackers, calendar connections, and integration
    connections as one JSON document.

    Integration access tokens are never exported (they can't be used on another
    instance); the connection config is exported so it only needs its token
    re-entered after import.
    """
    profile = await get_owned_profile(db, profile_id, current_user, "profile")
    rows = await load_profile_rows(db, profile_id)
    return build_profile_backup(profile=profile, **rows)


@router.post(
    "/profiles",
    status_code=status.HTTP_201_CREATED,
    summary="Import a profile backup as a new profile",
)
async def import_profile_backup(
    backup: ProfileBackup,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ImportSummary:
    """Recreate a backup document as a new profile owned by the current user.

    A new profile is always created (the imported name is suffixed if the user
    already has one by that name); nothing existing is overwritten. All foreign
    keys are remapped to the newly-created rows. Integration connections are
    imported disabled and tokenless — re-enter their PATs afterward.
    """
    try:
        return await restore_profile_backup(db, current_user, backup)
    except BackupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
