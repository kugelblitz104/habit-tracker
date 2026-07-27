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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
)
from habit_tracker.models.backup import ImportSummary, ProfileBackup
from habit_tracker.schemas.db_models import (
    CalendarConnection,
    Countdown,
    Habit,
    IntegrationConnection,
    Project,
    Task,
    TimeEntry,
    Tracker,
    User,
)
from habit_tracker.services.profile_backup import (
    BackupError,
    build_profile_backup,
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

    projects = (
        (await db.execute(
            select(Project)
            .where(Project.profile_id == profile_id)
            .order_by(Project.id)
        ))
        .scalars()
        .all()
    )
    tasks = (
        (await db.execute(
            select(Task).where(Task.profile_id == profile_id).order_by(Task.id)
        ))
        .scalars()
        .all()
    )
    countdowns = (
        (await db.execute(
            select(Countdown)
            .where(Countdown.profile_id == profile_id)
            .order_by(Countdown.id)
        ))
        .scalars()
        .all()
    )
    time_entries = (
        (await db.execute(
            select(TimeEntry)
            .where(TimeEntry.profile_id == profile_id)
            .order_by(TimeEntry.id)
        ))
        .scalars()
        .all()
    )
    habits = (
        (await db.execute(
            select(Habit)
            .where(Habit.profile_id == profile_id)
            .order_by(Habit.id)
        ))
        .scalars()
        .all()
    )
    trackers = (
        (await db.execute(
            select(Tracker)
            .join(Habit, Tracker.habit_id == Habit.id)
            .where(Habit.profile_id == profile_id)
            .order_by(Tracker.id)
        ))
        .scalars()
        .all()
    )
    calendar_connections = (
        (await db.execute(
            select(CalendarConnection)
            .where(CalendarConnection.profile_id == profile_id)
            .order_by(CalendarConnection.id)
        ))
        .scalars()
        .all()
    )
    integration_connections = (
        (await db.execute(
            select(IntegrationConnection)
            .where(IntegrationConnection.profile_id == profile_id)
            .order_by(IntegrationConnection.id)
        ))
        .scalars()
        .all()
    )

    return build_profile_backup(
        profile=profile,
        projects=projects,
        tasks=tasks,
        countdowns=countdowns,
        time_entries=time_entries,
        habits=habits,
        trackers=trackers,
        calendar_connections=calendar_connections,
        integration_connections=integration_connections,
    )


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
