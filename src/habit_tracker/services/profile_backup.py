"""Build and restore full-profile backups.

``build_profile_backup`` is pure: it takes already-loaded ORM rows and returns
the :class:`ProfileBackup` document, so it unit-tests without a database.

``restore_profile_backup`` recreates the document as a brand-new profile owned
by a given user, remapping every foreign key from the source ids to the rows it
inserts. It always creates a new profile (never merges into an existing one),
which keeps the semantics predictable: an import can't clobber or silently
dedupe against data already there. Insert order follows the dependency graph so
each foreign key resolves against rows created earlier in the same call:

    projects -> tasks (parents then subtasks) -> habits -> trackers
    -> time entries -> countdowns -> calendar connections -> integrations
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.models.backup import (
    BACKUP_FORMAT,
    BACKUP_VERSION,
    CalendarConnectionBackup,
    CountdownBackup,
    HabitBackup,
    ImportSummary,
    IntegrationConnectionBackup,
    ProfileBackup,
    ProfileSettings,
    ProjectBackup,
    TaskBackup,
    TimeEntryBackup,
    TrackerBackup,
)
from habit_tracker.schemas.db_models import (
    CalendarConnection,
    Countdown,
    Habit,
    IntegrationConnection,
    Profile,
    Project,
    Task,
    TimeEntry,
    Tracker,
    User,
)


class BackupError(Exception):
    """Raised when a backup document can't be restored (bad format/version)."""


async def load_profile_rows(db: AsyncSession, profile_id: int) -> dict:
    """Load every entity of a profile for a backup export.

    Returns a dict keyed by build_profile_backup's kwarg names, so the
    router can call ``build_profile_backup(profile=profile, **rows)``.
    Tracker has no profile_id column of its own, so its rows are reached by
    joining through Habit.
    """
    projects = (
        (
            await db.execute(
                select(Project)
                .where(Project.profile_id == profile_id)
                .order_by(Project.id)
            )
        )
        .scalars()
        .all()
    )
    tasks = (
        (
            await db.execute(
                select(Task).where(Task.profile_id == profile_id).order_by(Task.id)
            )
        )
        .scalars()
        .all()
    )
    countdowns = (
        (
            await db.execute(
                select(Countdown)
                .where(Countdown.profile_id == profile_id)
                .order_by(Countdown.id)
            )
        )
        .scalars()
        .all()
    )
    time_entries = (
        (
            await db.execute(
                select(TimeEntry)
                .where(TimeEntry.profile_id == profile_id)
                .order_by(TimeEntry.id)
            )
        )
        .scalars()
        .all()
    )
    habits = (
        (
            await db.execute(
                select(Habit).where(Habit.profile_id == profile_id).order_by(Habit.id)
            )
        )
        .scalars()
        .all()
    )
    trackers = (
        (
            await db.execute(
                select(Tracker)
                .join(Habit, Tracker.habit_id == Habit.id)
                .where(Habit.profile_id == profile_id)
                .order_by(Tracker.id)
            )
        )
        .scalars()
        .all()
    )
    calendar_connections = (
        (
            await db.execute(
                select(CalendarConnection)
                .where(CalendarConnection.profile_id == profile_id)
                .order_by(CalendarConnection.id)
            )
        )
        .scalars()
        .all()
    )
    integration_connections = (
        (
            await db.execute(
                select(IntegrationConnection)
                .where(IntegrationConnection.profile_id == profile_id)
                .order_by(IntegrationConnection.id)
            )
        )
        .scalars()
        .all()
    )

    return {
        "projects": projects,
        "tasks": tasks,
        "countdowns": countdowns,
        "time_entries": time_entries,
        "habits": habits,
        "trackers": trackers,
        "calendar_connections": calendar_connections,
        "integration_connections": integration_connections,
    }


def build_profile_backup(
    profile: Profile,
    projects: Iterable[Project],
    tasks: Iterable[Task],
    countdowns: Iterable[Countdown],
    time_entries: Iterable[TimeEntry],
    habits: Iterable[Habit],
    trackers: Iterable[Tracker],
    calendar_connections: Iterable[CalendarConnection],
    integration_connections: Iterable[IntegrationConnection],
    exported_at: datetime | None = None,
) -> ProfileBackup:
    """Assemble the portable backup document from loaded ORM rows (pure)."""
    return ProfileBackup(
        exported_at=exported_at or datetime.now(UTC),
        profile=ProfileSettings.model_validate(profile),
        projects=[ProjectBackup.model_validate(p) for p in projects],
        tasks=[TaskBackup.model_validate(t) for t in tasks],
        countdowns=[CountdownBackup.model_validate(c) for c in countdowns],
        time_entries=[TimeEntryBackup.model_validate(e) for e in time_entries],
        habits=[HabitBackup.model_validate(h) for h in habits],
        trackers=[TrackerBackup.model_validate(t) for t in trackers],
        calendar_connections=[
            CalendarConnectionBackup.model_validate(c) for c in calendar_connections
        ],
        integration_connections=[
            IntegrationConnectionBackup.model_validate(c)
            for c in integration_connections
        ],
    )


async def _unique_profile_name(db: AsyncSession, user_id: int, desired: str) -> str:
    """Pick a profile name unique for the user (``(user_id, name)`` is unique).

    Keeps the imported name when free; otherwise appends "(imported)" then
    "(imported 2)", "(imported 3)", … so re-importing the same backup never
    collides.
    """
    result = await db.execute(select(Profile.name).where(Profile.user_id == user_id))
    existing = {name for (name,) in result.all()}
    if desired not in existing:
        return desired
    candidate = f"{desired} (imported)"
    counter = 2
    while candidate in existing:
        candidate = f"{desired} (imported {counter})"
        counter += 1
    return candidate


async def restore_profile_backup(
    db: AsyncSession, user: User, backup: ProfileBackup
) -> ImportSummary:
    """Recreate a backup as a new profile owned by ``user``.

    Commits on success and returns per-entity counts. Raises ``BackupError`` for
    a document this server can't read (wrong format or a newer version).
    """
    if backup.format != BACKUP_FORMAT:
        raise BackupError(
            f"Unrecognized backup format {backup.format!r}; expected {BACKUP_FORMAT!r}."
        )
    if backup.version > BACKUP_VERSION:
        raise BackupError(
            f"Backup version {backup.version} is newer than this server "
            f"supports (max {BACKUP_VERSION}). Update the server and retry."
        )

    warnings: list[str] = []

    # Profile ----------------------------------------------------------------
    name = await _unique_profile_name(db, user.id, backup.profile.name)
    if name != backup.profile.name:
        warnings.append(
            f"A profile named {backup.profile.name!r} already existed; "
            f"imported as {name!r}."
        )
    profile = Profile(
        user_id=user.id,
        name=name,
        **backup.profile.model_dump(exclude={"name"}),
    )
    db.add(profile)
    await db.flush()

    # Projects ---------------------------------------------------------------
    project_map: dict[int, int] = {}
    for item in backup.projects:
        row = Project(
            profile_id=profile.id,
            **item.model_dump(exclude={"id"}, exclude_none=True),
        )
        db.add(row)
        await db.flush()
        project_map[item.id] = row.id

    # Tasks: parents first so a subtask's parent_id resolves in task_map ------
    task_map: dict[int, int] = {}
    parents = [t for t in backup.tasks if t.parent_id is None]
    children = [t for t in backup.tasks if t.parent_id is not None]
    tasks_imported = 0
    subtasks_imported = 0
    for item in parents:
        row = Task(
            profile_id=profile.id,
            project_id=(
                project_map.get(item.project_id)
                if item.project_id is not None
                else None
            ),
            parent_id=None,
            **item.model_dump(
                exclude={"id", "project_id", "parent_id"}, exclude_none=True
            ),
        )
        db.add(row)
        await db.flush()
        task_map[item.id] = row.id
        tasks_imported += 1
    for item in children:
        # item.parent_id is never None here (children was filtered above),
        # but TaskBackup.parent_id is typed int | None; the ternary narrows
        # it for basedpyright without changing behavior (task_map.get(None)
        # would already return None, same as the else branch below).
        parent_new_id = (
            task_map.get(item.parent_id) if item.parent_id is not None else None
        )
        if parent_new_id is None:
            # Parent missing from the backup (shouldn't happen) — keep the
            # subtask rather than drop it, promoted to top level.
            warnings.append(
                f"Subtask {item.title!r} referenced a missing parent; "
                f"imported as a top-level task."
            )
        row = Task(
            profile_id=profile.id,
            project_id=(
                project_map.get(item.project_id)
                if item.project_id is not None
                else None
            ),
            parent_id=parent_new_id,
            **item.model_dump(
                exclude={"id", "project_id", "parent_id"}, exclude_none=True
            ),
        )
        db.add(row)
        await db.flush()
        task_map[item.id] = row.id
        subtasks_imported += 1

    # Habits -----------------------------------------------------------------
    habit_map: dict[int, int] = {}
    for item in backup.habits:
        row = Habit(
            profile_id=profile.id,
            **item.model_dump(exclude={"id"}, exclude_none=True),
        )
        db.add(row)
        await db.flush()
        habit_map[item.id] = row.id

    # Trackers ---------------------------------------------------------------
    trackers_imported = 0
    for item in backup.trackers:
        habit_new_id = habit_map.get(item.habit_id)
        if habit_new_id is None:
            warnings.append(
                f"Skipped a tracker dated {item.dated.isoformat()}: its habit "
                f"was not in the backup."
            )
            continue
        row = Tracker(
            habit_id=habit_new_id,
            **item.model_dump(exclude={"id", "habit_id"}, exclude_none=True),
        )
        db.add(row)
        trackers_imported += 1

    # Time entries -----------------------------------------------------------
    for item in backup.time_entries:
        row = TimeEntry(
            profile_id=profile.id,
            task_id=(task_map.get(item.task_id) if item.task_id is not None else None),
            project_id=(
                project_map.get(item.project_id)
                if item.project_id is not None
                else None
            ),
            **item.model_dump(
                exclude={"id", "task_id", "project_id"}, exclude_none=True
            ),
        )
        db.add(row)

    # Countdowns -------------------------------------------------------------
    for item in backup.countdowns:
        row = Countdown(
            profile_id=profile.id,
            task_id=(task_map.get(item.task_id) if item.task_id is not None else None),
            **item.model_dump(exclude={"id", "task_id"}, exclude_none=True),
        )
        db.add(row)

    # Calendar connections (cache fields are refetched, not imported) --------
    for item in backup.calendar_connections:
        row = CalendarConnection(
            profile_id=profile.id,
            **item.model_dump(exclude={"id"}, exclude_none=True),
        )
        db.add(row)

    # Integration connections: config only. The PAT can't cross instances, so
    # recreate disabled + tokenless (empty string -> has_token is False) for
    # the user to re-enter.
    integrations_imported = 0
    for item in backup.integration_connections:
        row = IntegrationConnection(
            profile_id=profile.id,
            encrypted_token="",
            enabled=False,
            **item.model_dump(
                exclude={"id", "has_token", "enabled"}, exclude_none=True
            ),
        )
        db.add(row)
        integrations_imported += 1
        if item.has_token:
            warnings.append(
                f"Integration {item.name!r} was imported disabled — re-enter "
                f"its access token, which can't be moved between instances."
            )

    await db.commit()

    return ImportSummary(
        success=True,
        profile_id=profile.id,
        profile_name=profile.name,
        projects_imported=len(project_map),
        tasks_imported=tasks_imported,
        subtasks_imported=subtasks_imported,
        countdowns_imported=len(backup.countdowns),
        time_entries_imported=len(backup.time_entries),
        habits_imported=len(habit_map),
        trackers_imported=trackers_imported,
        calendar_connections_imported=len(backup.calendar_connections),
        integration_connections_imported=integrations_imported,
        warnings=warnings,
    )
