from typing import List

from pydantic import BaseModel


class ImportedHabitSummary(BaseModel):
    """Summary of an imported habit"""

    original_name: str
    new_habit_id: int
    trackers_imported: int


class ImportResult(BaseModel):
    """Result of a database import operation"""

    success: bool
    message: str
    habits_imported: int
    trackers_imported: int
    habits_skipped: int
    trackers_skipped: int
    details: List[ImportedHabitSummary] = []
    errors: List[str] = []


class ExportResult(BaseModel):
    """Result of a database export operation containing the file as base64"""

    filename: str
    data: str  # base64-encoded SQLite .db file
    content_type: str = "application/x-sqlite3"
