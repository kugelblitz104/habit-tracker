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
    details: list[ImportedHabitSummary] = []
    errors: list[str] = []


class JournalImportResult(BaseModel):
    """Result of importing an Obsidian daily-notes vault.

    Its own model rather than ImportResult, whose counts are habit-specific.
    `warnings` names every file that was skipped or imported degraded, one
    line each.
    """

    entries_imported: int
    entries_skipped: int
    files_failed: int
    warnings: list[str] = []


class ExportResult(BaseModel):
    """Result of a database export operation containing the file as base64"""

    filename: str
    data: str  # base64-encoded SQLite .db file
    content_type: str = "application/x-sqlite3"
