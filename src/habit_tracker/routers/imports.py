import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import get_current_user, get_db
from habit_tracker.models.habits import loopHabitColors
from habit_tracker.models.imports import ImportedHabitSummary, ImportResult
from habit_tracker.schemas.db_models import Habit, Tracker, User

router = APIRouter(
    prefix="/import",
    tags=["import"],
    responses={404: {"description": "Not found"}},
)

# Mapping from Loop Habit Tracker color indices to hex colors
# The external app uses integer indices 0-19 to represent colors


def map_color(color_index: int) -> str:
    """Map Loop Habit Tracker color index to hex color code."""
    if 0 <= color_index < len(loopHabitColors):
        return loopHabitColors[color_index]
    # Default to blue if index is out of range
    return "#1976D2"


def reverse_map_color(hex_color: str) -> int:
    """Map hex color code back to Loop Habit Tracker color index."""
    hex_upper = hex_color.upper()
    for index, color in enumerate(loopHabitColors):
        if color.upper() == hex_upper:
            return index
    # Default to blue (index 11) if not found
    return 11


def date_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime to Loop Habit Tracker timestamp.
    Loop Habit Tracker uses milliseconds since epoch.
    """
    return int(dt.timestamp() * 1000)


def timestamp_to_date(timestamp: int) -> datetime:
    """
    Convert Loop Habit Tracker timestamp to datetime.
    Loop Habit Tracker uses milliseconds since epoch.
    """
    return datetime.fromtimestamp(timestamp / 1000)


@router.post(
    "/loop-habit-tracker",
    status_code=status.HTTP_201_CREATED,
    summary="Import habits from Loop Habit Tracker",
)
async def import_from_loop_habit_tracker(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(..., description="SQLite .db file from Loop Habit Tracker"),
) -> ImportResult:
    """
    Import habits and their tracking history from a Loop Habit Tracker database file.

    The file should be a SQLite .db file exported from Loop Habit Tracker app.

    **Mapping from Loop Habit Tracker to this app:**
    - `name` → `name`
    - `question` → `question` (or generated from name if empty)
    - `color` → `color` (mapped from index to hex)
    - `freq_num` → `frequency`
    - `freq_den` → `range`
    - `archived` → `archived`
    - `position` → `sort_order`
    - Repetitions with `value >= 2` → Tracker with `completed=True`
    - Repetitions with `value == 1` → Tracker with `skipped=True`
    - Repetitions `notes` → Tracker `note`
    """
    # Validate file extension
    if not file.filename or not file.filename.endswith(".db"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .db SQLite database file",
        )

    # Save uploaded file to a temporary location
    temp_file = None
    try:
        content = await file.read()

        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
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

        # Get the maximum sort_order for the current user's habits
        max_sort_order_result = await db.execute(
            select(func.coalesce(func.max(Habit.sort_order), -1)).where(
                Habit.user_id == current_user.id
            )
        )
        current_max_sort_order = max_sort_order_result.scalar() or -1

        # Read habits from the imported database
        cursor.execute(
            """
            SELECT id, archived, color, description, freq_den, freq_num, 
                   name, position, question
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
        habit_id_mapping: dict[int, int] = {}  # old_id -> new_id

        for habit_row in imported_habits:
            try:
                old_habit_id = habit_row["id"]
                name = habit_row["name"] or "Unnamed Habit"
                question = habit_row["question"] or f"Did you {name.lower()} today?"
                color = map_color(habit_row["color"] or 0)
                frequency = habit_row["freq_num"] or 1
                range_val = habit_row["freq_den"] or 1
                archived = bool(habit_row["archived"])

                # Create new habit
                current_max_sort_order += 1
                new_habit = Habit(
                    user_id=current_user.id,
                    name=name,
                    question=question,
                    color=color,
                    frequency=frequency,
                    range=range_val,
                    reminder=False,  # Loop Habit Tracker reminders not imported
                    notes=habit_row["description"],
                    archived=archived,
                    sort_order=current_max_sort_order,
                )
                db.add(new_habit)
                await db.flush()  # Get the new ID

                habit_id_mapping[old_habit_id] = new_habit.id

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

                        # Loop Habit Tracker values:
                        # 0 = not done
                        # 1 = skipped (with skip button)
                        # 2 = done
                        # For numerical habits, value can be higher
                        if value == 0:
                            # Not completed - skip importing
                            trackers_skipped += 1
                            continue

                        completed = value >= 2
                        skipped = value == 1

                        new_tracker = Tracker(
                            habit_id=new_habit.id,
                            dated=rep_date,
                            completed=completed,
                            skipped=skipped,
                            note=notes,
                        )
                        db.add(new_tracker)
                        habit_trackers_imported += 1
                        trackers_imported += 1

                    except Exception as e:
                        trackers_skipped += 1
                        errors.append(
                            f"Failed to import tracker for habit '{name}': {str(e)}"
                        )

                habits_imported += 1
                details.append(
                    ImportedHabitSummary(
                        original_name=name,
                        new_habit_id=new_habit.id,
                        trackers_imported=habit_trackers_imported,
                    )
                )

            except Exception as e:
                habits_skipped += 1
                habit_name = habit_row["name"] if habit_row else "Unknown"
                errors.append(f"Failed to import habit '{habit_name}': {str(e)}")

        # Commit all changes
        await db.commit()
        conn.close()

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
            detail=f"Invalid SQLite database: {str(e)}",
        )

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}",
        )

    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


@router.get(
    "/loop-habit-tracker",
    summary="Export habits to Loop Habit Tracker format",
    response_class=FileResponse,
)
async def export_to_loop_habit_tracker(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
) -> FileResponse:
    """
    Export habits and their tracking history to a Loop Habit Tracker compatible database file.

    Returns a SQLite .db file that can be imported into Loop Habit Tracker app.

    **Query Parameters:**
    - `include_archived`: Whether to include archived habits (default: False)

    **Mapping from this app to Loop Habit Tracker:**
    - `name` → `name`
    - `question` → `question`
    - `color` (#hex) → `color` (0-19 index)
    - `frequency` → `freq_num`
    - `range` → `freq_den`
    - `archived` → `archived`
    - `sort_order` → `position`
    - `notes` → `description`
    - Tracker with `completed=True` → Repetition with `value=2`
    - Tracker with `skipped=True` → Repetition with `value=1`
    - Tracker `note` → Repetition `notes`
    """
    temp_file = None
    try:
        # Create a temporary file for the export database
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
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
        query = select(Habit).where(Habit.user_id == current_user.id)
        if not include_archived:
            query = query.where(Habit.archived == False)  # noqa: E712
        query = query.order_by(Habit.sort_order)

        result = await db.execute(query)
        habits = result.scalars().all()

        habit_id_mapping: dict[int, int] = {}  # our_id -> loop_id

        for position, habit in enumerate(habits):
            # Generate a UUID for the habit
            habit_uuid = str(uuid.uuid4())

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
                    0,  # default reminder hour
                    0,  # default reminder minute
                    0,  # reminder_days
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
            habit_id_mapping[habit.id] = loop_habit_id

            # Fetch trackers for this habit
            tracker_result = await db.execute(
                select(Tracker)
                .where(Tracker.habit_id == habit.id)
                .order_by(Tracker.dated)
            )
            trackers = tracker_result.scalars().all()

            for tracker in trackers:
                # Convert tracker to repetition
                # Loop Habit Tracker values:
                # 0 = not done
                # 1 = skipped
                # 2 = done
                if tracker.skipped:
                    value = 1
                elif tracker.completed:
                    value = 2
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

        # Generate filename with timestamp
        export_filename = f"habits_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

        return FileResponse(
            path=temp_file.name,
            filename=export_filename,
            media_type="application/x-sqlite3",
            background=None,  # Don't delete immediately, let cleanup handle it
        )

    except Exception as e:
        # Clean up on error
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}",
        )
