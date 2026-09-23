import base64
import io
import os
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.dependencies import (
    get_current_user,
    get_db,
    get_owned_profile,
    resolve_habit_profile_id,
)
from habit_tracker.core.slugs import allocate_slug
from habit_tracker.models.imports import (
    ExportResult,
    ImportedHabitSummary,
    ImportResult,
    JournalImportResult,
)
from habit_tracker.schemas.db_models import (
    Habit,
    JournalEntry,
    Profile,
    Tracker,
    User,
)
from habit_tracker.services.journal_import import (
    TEMPLATE_FILENAME,
    parse_journal_file,
)
from habit_tracker.services.loop_format import map_color, reverse_map_color

router = APIRouter(
    prefix="/import",
    tags=["import"],
    responses={404: {"description": "Not found"}},
)


def date_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime to Loop Habit Tracker timestamp.
    Loop Habit Tracker uses milliseconds since epoch at midnight UTC.
    """
    return int(dt.replace(tzinfo=UTC).timestamp() * 1000)


def timestamp_to_date(timestamp: int) -> datetime:
    """
    Convert Loop Habit Tracker timestamp to datetime.

    Loop stores repetition timestamps as milliseconds since epoch at midnight
    UTC of the tracked day, so decode in UTC — a server-local decode shifts
    every date back one day in any negative-offset timezone.
    """
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC)


def map_repetition_value(value: int) -> TrackerStatus | None:
    """
    Map a Loop Habit Tracker repetition value to a TrackerStatus.

    Loop's value semantics vary by app version:
    - 0 = not done (all versions) — never imported
    - 1 = skipped (older exports) — SKIPPED
    - 2 = done / YES_MANUAL — COMPLETED
    - 3 = SKIP (Loop 2.x) — SKIPPED
    - >3 = numerical habits store amount x 1000 — COMPLETED

    Returns None for values that should not create a tracker. Writing the raw
    value into Tracker.status would corrupt the column for 3 and numerical
    amounts, so everything is clamped to the app's enum here.
    """
    if value <= 0:
        return None
    if value in (1, 3):
        return TrackerStatus.SKIPPED
    return TrackerStatus.COMPLETED


# Loop packs its weekdays Saturday-first (bit 0 = Saturday ... bit 6 = Friday);
# Habit.reminder_days is Monday-first, so Loop bit i is our bit (i + 5) % 7.
def mask_from_loop(loop_mask: int) -> int:
    """Convert a Loop reminder_days mask to Habit.reminder_days."""
    if not loop_mask & 127:
        return 127  # Loop treats an empty day set as every day
    return sum(1 << ((i + 5) % 7) for i in range(7) if loop_mask >> i & 1)


def mask_to_loop(mask: int) -> int:
    """Convert Habit.reminder_days to a Loop reminder_days mask."""
    return sum(1 << ((j + 2) % 7) for j in range(7) if mask >> j & 1)


def loop_reminder_time(hour: int | None, minute: int | None) -> time | None:
    """Loop's reminder_hour/reminder_min as a time, or None when Loop's reminder
    is off (a null hour) or the values are out of range."""
    if hour is None or not 0 <= hour <= 23 or not 0 <= (minute or 0) <= 59:
        return None
    return time(hour, minute or 0)


@router.post(
    "/loop-habit-tracker",
    status_code=status.HTTP_201_CREATED,
    summary="Import habits from Loop Habit Tracker",
)
async def import_from_loop_habit_tracker(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(..., description="SQLite .db file from Loop Habit Tracker"),
    profile_id: int | None = Query(
        default=None,
        description=(
            "Profile the imported habits belong to. Must belong to the "
            "current user; defaults to the user's oldest profile if omitted."
        ),
    ),
) -> ImportResult:
    """
    Import habits and their tracking history from a Loop Habit Tracker database file.

    The file should be a SQLite .db file exported from Loop Habit Tracker app.

    - **profile_id**: Optional target profile for the imported habits. Must
      belong to the current user; defaults to the user's oldest profile

    **Mapping from Loop Habit Tracker to this app:**
    - `name` → `name`
    - `question` → `question` (or generated from name if empty)
    - `color` → `color` (mapped from index to hex)
    - `freq_num` → `frequency`
    - `freq_den` → `range`
    - `archived` → `archived`
    - `position` → `sort_order`
    - Repetitions `value` → Tracker `status` (1/3 = skipped, 2+ = completed)
    - Repetitions `notes` → Tracker `note`
    """
    resolved_profile_id = await resolve_habit_profile_id(
        db, current_user.id, profile_id
    )

    # Validate file extension
    if not file.filename or not file.filename.endswith(".db"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .db SQLite database file",
        )

    # Save uploaded file to a temporary location
    temp_file = None
    conn = None
    try:
        content = await file.read()

        # Create a temporary file. Not a `with` block (SIM115): the path
        # outlives this statement - it is reopened by sqlite3 below - and is
        # only unlinked in the `finally` at the bottom of this function
        # (after the sqlite connection is closed, since on Windows an open
        # connection blocks the unlink).
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")  # noqa: SIM115
        temp_file.write(content)
        temp_file.close()

        # Open the SQLite database
        conn = sqlite3.connect(temp_file.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Verify the database has the expected tables
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='Habits'"
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid database: 'Habits' table not found",
            )

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='Repetitions'"
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid database: 'Repetitions' table not found",
            )

        # Get the maximum sort_order within the target profile so imported
        # habits append after the profile's existing list
        max_sort_order_result = await db.execute(
            select(func.coalesce(func.max(Habit.sort_order), -1)).where(
                Habit.profile_id == resolved_profile_id,
            )
        )
        current_max_sort_order = max_sort_order_result.scalar() or -1

        # Read habits from the imported database
        cursor.execute(
            """
            SELECT id, archived, color, description, freq_den, freq_num,
                   name, position, question, reminder_hour, reminder_min,
                   reminder_days
            FROM Habits
            ORDER BY position
        """
        )
        imported_habits = cursor.fetchall()

        habits_imported = 0
        habits_skipped = 0
        trackers_imported = 0
        trackers_skipped = 0
        details: list[ImportedHabitSummary] = []
        errors: list[str] = []

        for habit_row in imported_habits:
            try:
                old_habit_id = habit_row["id"]
                name = habit_row["name"] or "Unnamed Habit"
                question = habit_row["question"] or f"Did you {name.lower()} today?"
                color = map_color(habit_row["color"] or 0)
                frequency = habit_row["freq_num"] or 1
                range_val = habit_row["freq_den"] or 1
                archived = bool(habit_row["archived"])
                reminder_time = loop_reminder_time(
                    habit_row["reminder_hour"], habit_row["reminder_min"]
                )

                # Create new habit
                current_max_sort_order += 1
                new_habit = Habit(
                    profile_id=resolved_profile_id,
                    name=name,
                    slug=await allocate_slug(
                        db, Habit, profile_id=resolved_profile_id, source=name
                    ),
                    question=question,
                    color=color,
                    frequency=frequency,
                    range=range_val,
                    reminder=reminder_time is not None,
                    reminder_time=reminder_time,
                    reminder_days=(
                        mask_from_loop(habit_row["reminder_days"])
                        if reminder_time is not None
                        else 127
                    ),
                    notes=habit_row["description"],
                    archived=archived,
                    sort_order=current_max_sort_order,
                )
                db.add(new_habit)
                await db.flush()  # Get the new ID

                # Import repetitions (trackers) for this habit
                cursor.execute(
                    """
                    SELECT timestamp, value, notes
                    FROM Repetitions
                    WHERE habit = ?
                    ORDER BY timestamp
                """,
                    (old_habit_id,),
                )
                repetitions = cursor.fetchall()

                habit_trackers_imported = 0
                seen_dates: set[str] = set()

                for rep in repetitions:
                    try:
                        timestamp = rep["timestamp"]
                        value = rep["value"]
                        notes = rep["notes"]

                        # Convert timestamp to date
                        rep_datetime = timestamp_to_date(timestamp)
                        rep_date = rep_datetime.date()
                        date_key = rep_date.isoformat()

                        # Skip duplicate dates (keep first occurrence)
                        if date_key in seen_dates:
                            trackers_skipped += 1
                            continue
                        seen_dates.add(date_key)

                        mapped_status = map_repetition_value(value)
                        if mapped_status is None:
                            # Not completed - skip importing
                            trackers_skipped += 1
                            continue

                        new_tracker = Tracker(
                            habit_id=new_habit.id,
                            dated=rep_date,
                            status=mapped_status,
                            note=notes,
                        )
                        db.add(new_tracker)
                        habit_trackers_imported += 1
                        trackers_imported += 1

                    except Exception as e:  # noqa: BLE001 - one bad row (of
                        # arbitrary shape from a user-uploaded SQLite export)
                        # must not abort the rest of the import; the failure
                        # is recorded and the loop continues.
                        trackers_skipped += 1
                        errors.append(
                            f"Failed to import tracker for habit '{name}': {e!s}"
                        )

                habits_imported += 1
                details.append(
                    ImportedHabitSummary(
                        original_name=name,
                        new_habit_id=new_habit.id,
                        trackers_imported=habit_trackers_imported,
                    )
                )

            except Exception as e:  # noqa: BLE001 - same per-row resilience
                # as the tracker loop above: skip this habit, keep importing.
                habits_skipped += 1
                habit_name = habit_row["name"] if habit_row else "Unknown"
                errors.append(f"Failed to import habit '{habit_name}': {e!s}")

        # Commit all changes
        await db.commit()

        return ImportResult(
            success=True,
            message=f"Successfully imported {habits_imported} habits and {trackers_imported} trackers",
            habits_imported=habits_imported,
            trackers_imported=trackers_imported,
            habits_skipped=habits_skipped,
            trackers_skipped=trackers_skipped,
            details=details,
            errors=errors,
        )

    except HTTPException:
        raise

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid SQLite database: {e!s}",
        )

    except Exception as e:  # noqa: BLE001 - top-level catch-all converting
        # any unexpected failure into a 500 rather than an unhandled error.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {e!s}",
        )

    finally:
        # Close the sqlite connection on ALL paths (early HTTPExceptions
        # included) - on Windows an open connection blocks the unlink below
        if conn is not None:
            conn.close()
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


@router.get(
    "/loop-habit-tracker",
    summary="Export habits to Loop Habit Tracker format",
)
async def export_to_loop_habit_tracker(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
    profile_id: int | None = Query(
        default=None,
        description=(
            "Only export habits belonging to this profile. Must belong to "
            "the current user; omit to export all of the user's habits."
        ),
    ),
) -> ExportResult:
    """
    Export habits and their tracking history to a Loop Habit Tracker compatible database file.

    Returns a SQLite .db file that can be imported into Loop Habit Tracker app.

    **Query Parameters:**
    - `include_archived`: Whether to include archived habits (default: False)
    - `profile_id`: Only export this profile's habits (default: all profiles)

    **Mapping from this app to Loop Habit Tracker:**
    - `name` → `name`
    - `question` → `question`
    - `color` (#hex) → `color` (0-19 index)
    - `frequency` → `freq_num`
    - `range` → `freq_den`
    - `archived` → `archived`
    - `sort_order` → `position`
    - `notes` → `description`
    - Tracker `status` → Repetition `value` (3 = skipped, 2 = completed)
    - Tracker `note` → Repetition `notes`
    """
    # Authorize the profile filter before touching the filesystem (404/403
    # from get_owned_profile must not be swallowed by the except below)
    if profile_id is not None:
        await get_owned_profile(db, profile_id, current_user, "profile")

    temp_file = None
    conn = None
    try:
        # Create a temporary file for the export database. Not a `with`
        # block (SIM115): the path outlives this statement - it is reopened
        # by sqlite3 below and again by the base64 read further down, and
        # only unlinked in the `finally` at the bottom of this function
        # (after the sqlite connection is closed, since on Windows an open
        # connection blocks the unlink).
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")  # noqa: SIM115
        temp_file.close()

        # Create the SQLite database with Loop Habit Tracker schema
        conn = sqlite3.connect(temp_file.name)
        cursor = conn.cursor()

        # Create Habits table matching Loop Habit Tracker schema
        cursor.execute("""
            CREATE TABLE Habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archived INTEGER,
                color INTEGER,
                description TEXT,
                freq_den INTEGER,
                freq_num INTEGER,
                highlight INTEGER,
                name TEXT,
                position INTEGER,
                reminder_hour INTEGER,
                reminder_min INTEGER,
                reminder_days INTEGER NOT NULL DEFAULT 127,
                type INTEGER NOT NULL DEFAULT 0,
                target_type INTEGER NOT NULL DEFAULT 0,
                target_value REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT "",
                question TEXT,
                uuid TEXT
            )
        """)

        # Create Repetitions table matching Loop Habit Tracker schema
        cursor.execute("""
            CREATE TABLE Repetitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit INTEGER NOT NULL REFERENCES Habits(id),
                timestamp INTEGER NOT NULL,
                value INTEGER NOT NULL,
                notes TEXT
            )
        """)

        # Fetch user's habits
        query = (
            select(Habit)
            .join(Profile, Habit.profile_id == Profile.id)
            .where(Profile.user_id == current_user.id)
        )
        if profile_id is not None:
            query = query.where(Habit.profile_id == profile_id)
        if not include_archived:
            query = query.where(Habit.archived == False)
        query = query.order_by(Habit.sort_order)

        result = await db.execute(query)
        habits = result.scalars().all()

        for position, habit in enumerate(habits):
            # Generate a UUID for the habit
            habit_uuid = str(uuid.uuid4())
            # Loop reads a non-null hour as "reminder on", so an off reminder,
            # or one with no time, is written as NULL.
            reminder_time = habit.reminder_time if habit.reminder else None

            # Insert habit into export database
            cursor.execute(
                """
                INSERT INTO Habits (
                    archived, color, description, freq_den, freq_num,
                    highlight, name, position, reminder_hour, reminder_min,
                    reminder_days, type, target_type, target_value, unit,
                    question, uuid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    1 if habit.archived else 0,
                    reverse_map_color(habit.color),
                    habit.notes,
                    habit.range,  # freq_den
                    habit.frequency,  # freq_num
                    0,  # highlight
                    habit.name,
                    position,
                    reminder_time.hour if reminder_time else None,
                    reminder_time.minute if reminder_time else None,
                    mask_to_loop(habit.reminder_days) if reminder_time else 127,
                    0,  # type (boolean habit)
                    0,  # target_type
                    0.0,  # target_value
                    "",  # unit
                    habit.question,
                    habit_uuid,
                ),
            )

            loop_habit_id = cursor.lastrowid
            if loop_habit_id is None:
                continue

            # Fetch trackers for this habit
            tracker_result = await db.execute(
                select(Tracker)
                .where(Tracker.habit_id == habit.id)
                .order_by(Tracker.dated)
            )
            trackers = tracker_result.scalars().all()

            for tracker in trackers:
                # Convert tracker to repetition using Loop 2.x semantics
                # (0 = not done, 2 = done, 3 = skip); our import accepts both
                # the old 1 and the new 3 for skips, so round-trips are safe
                if tracker.status == TrackerStatus.SKIPPED:
                    value = 3
                elif tracker.status == TrackerStatus.COMPLETED:
                    value = 2
                elif tracker.note is not None:
                    value = 0
                else:
                    # Not completed and not skipped - skip export
                    continue

                # Convert date to timestamp (midnight of that day)
                tracker_datetime = datetime.combine(tracker.dated, datetime.min.time())
                timestamp = date_to_timestamp(tracker_datetime)

                cursor.execute(
                    """
                    INSERT INTO Repetitions (habit, timestamp, value, notes)
                    VALUES (?, ?, ?, ?)
                """,
                    (loop_habit_id, timestamp, value, tracker.note),
                )

        conn.commit()
        conn.close()
        conn = None

        # Generate filename with timestamp
        export_filename = f"habits_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

        # Read the file and encode as base64 for JSON transport. Blocking
        # open() (ASYNC230): this reads back the small SQLite export file
        # this same function just wrote via the equally-blocking sqlite3
        # driver, so switching only this read to threaded/async I/O would
        # not remove the blocking sqlite3 calls above it - not worth the
        # added complexity for a bounded, one-profile export file.
        with open(temp_file.name, "rb") as f:  # noqa: ASYNC230
            encoded_data = base64.b64encode(f.read()).decode("ascii")

        return ExportResult(
            filename=export_filename,
            data=encoded_data,
        )

    except Exception as e:  # noqa: BLE001 - top-level catch-all converting
        # any unexpected failure into a 500 rather than an unhandled error.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {e!s}",
        )

    finally:
        # Close the sqlite connection on ALL paths - on Windows an open
        # connection blocks the unlink below
        if conn is not None:
            conn.close()
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


# Guards on an uploaded vault. A real vault is 661 files of a few KB each;
# these bound a crafted archive without rejecting a real one. The per-note
# read cap is the one that matters, since a zip header's declared size can
# lie about what a member actually decompresses to.
MAX_VAULT_FILES = 2000
MAX_VAULT_BYTES = 50 * 1024 * 1024
MAX_NOTE_BYTES = 1 * 1024 * 1024


@router.post(
    "/journal",
    status_code=status.HTTP_201_CREATED,
    summary="Import journal entries from an Obsidian daily-notes folder",
)
async def import_journal_from_obsidian(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(..., description="Zip of the Obsidian daily-notes folder"),
    profile_id: int = Query(description="The profile the entries belong to"),
) -> JournalImportResult:
    """
    Import daily notes from a zipped Obsidian daily-notes folder.

    - **file**: A zip of the folder, one `YYYY-MM-DD.md` per day
    - **profile_id**: The profile the entries belong to (required)

    The filename gives the day. `daily.md` and any note inside a
    subdirectory are not daily notes and are ignored.

    **Mapping from a daily note to a journal entry:**
    - Prose under `**How did today go?**` -> `body`
    - Prose under `**Something you're grateful for?**` -> `gratitude`
    - The `[day_quality::...]` inline field -> `day_quality`, mapped onto the
      app's vocabulary. An unrecognised value imports the entry without one.
    - A note with neither prompt nor field is free prose and becomes `body`
      whole.
    - Dataview query blocks are dropped: they resolve inside Obsidian and
      carry no data.

    A day that already has an entry is left untouched, never overwritten,
    and one unreadable file does not abort the run. Both are reported in
    `warnings`.
    """
    await get_owned_profile(db, profile_id, current_user, "journal entry")

    content = await file.read()
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .zip archive",
        ) from None

    entries_imported = 0
    entries_skipped = 0
    files_failed = 0
    warnings: list[str] = []

    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_VAULT_FILES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Archive holds more than {MAX_VAULT_FILES} files",
            )
        if sum(info.file_size for info in members) > MAX_VAULT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Archive is larger than 50 MB uncompressed",
            )

        existing_result = await db.execute(
            select(JournalEntry.entry_date).where(JournalEntry.profile_id == profile_id)
        )
        taken_days = set(existing_result.scalars().all())

        for info in members:
            name = info.filename
            # Nothing is written to disk, so a crafted member name cannot
            # escape anywhere; these are skipped because a note in a
            # subdirectory is not a daily note.
            if "/" in name or "\\" in name or name.lower() == TEMPLATE_FILENAME:
                continue
            try:
                with archive.open(info) as member:
                    data = member.read(MAX_NOTE_BYTES + 1)
                if len(data) > MAX_NOTE_BYTES:
                    raise ValueError("larger than 1 MB")
                parsed = parse_journal_file(name, data.decode("utf-8"))
            except Exception as e:  # noqa: BLE001 - one unreadable member of
                # a user-uploaded archive must not abort a 900-day import;
                # the failure is recorded and the walk continues.
                files_failed += 1
                warnings.append(f"{name}: could not be read ({e!s})")
                continue

            if parsed is None:
                files_failed += 1
                warnings.append(f"{name}: filename is not a date (YYYY-MM-DD.md)")
                continue
            if parsed.entry_date in taken_days:
                entries_skipped += 1
                warnings.append(
                    f"{name}: {parsed.entry_date.isoformat()} already has an"
                    " entry, left unchanged"
                )
                continue

            taken_days.add(parsed.entry_date)
            warnings.extend(parsed.warnings)
            db.add(
                JournalEntry(
                    profile_id=profile_id,
                    entry_date=parsed.entry_date,
                    body=parsed.body,
                    gratitude=parsed.gratitude,
                    day_quality=parsed.day_quality,
                )
            )
            entries_imported += 1

    await db.commit()

    return JournalImportResult(
        entries_imported=entries_imported,
        entries_skipped=entries_skipped,
        files_failed=files_failed,
        warnings=warnings,
    )
