"""Pure parsing of Obsidian daily notes into journal entries.

Takes one ``(filename, text)`` pair at a time and returns a ``ParsedEntry``:
no zip, no database, no HTTP. The zip walking and the writes live in
``routers/imports.py``.

The vault has two eras. Templated notes are Dataview inline fields under
bold prompts::

    **How did today go?**
    [day_quality::good]
    played some games after a workout

    **Something you're grateful for?**
    sydney for making dinner

    #### Tasks completed today:
    ```dataview
    ...
    ```

Everything from the first Markdown heading onward is Dataview scaffolding:
those blocks are queries that resolve inside Obsidian, so they are dropped
rather than stored. Older notes are free prose with no structure, and are
taken whole as the body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from habit_tracker.constants import DayQuality

# The vault's own template file, which is not a daily note.
TEMPLATE_FILENAME = "daily.md"

_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$", re.IGNORECASE)

# Matches the inline field anywhere in the document, not only at line start:
# a few of the vault's 521 sit at the end of a prose line. Tolerates the
# double-bracket wikilink form, surrounding whitespace, a single colon
# (2025-03-30.md) and the day_guality transposition (2025-04-16.md).
_QUALITY_RE = re.compile(
    r"\[{1,2}day_[gq]uality::?\s*([^\]]*?)\s*\]{1,2}", re.IGNORECASE
)

_BODY_PROMPT = "how did today go?"
_GRATITUDE_PROMPT = "something you're grateful for?"

_VALID_QUALITIES = {q.value for q in DayQuality}

# The vault's words that are not DayQuality members. Covers all 519 values
# observed; anything else warns and imports without a quality.
_QUALITY_ALIASES = {
    "meh": DayQuality.GOOD.value,
    "mid": DayQuality.GOOD.value,
    "bad": DayQuality.ROUGH.value,
    "poor": DayQuality.ROUGH.value,
    "blech": DayQuality.DRAINING.value,
}


@dataclass
class ParsedEntry:
    """One daily note, ready to become a ``JournalEntry`` row."""

    entry_date: date
    body: str | None = None
    gratitude: str | None = None
    day_quality: str | None = None
    warnings: list[str] = field(default_factory=list)


def parse_entry_date(filename: str) -> date | None:
    """The calendar day a daily-note filename addresses.

    Returns None for the vault template, for a name in a subdirectory and
    for anything that is not ``YYYY-MM-DD.md``.
    """
    if "/" in filename or "\\" in filename:
        return None
    if filename.lower() == TEMPLATE_FILENAME:
        return None
    match = _FILENAME_RE.match(filename)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_journal_file(filename: str, text: str) -> ParsedEntry | None:
    """Parse one daily note, or return None when the file is not one.

    - ``filename``: gives the entry date, ``YYYY-MM-DD.md``
    - ``text``: the note's content

    An unrecognised ``day_quality`` value is reported in ``warnings`` and
    leaves ``day_quality`` None; it never guesses.
    """
    entry_date = parse_entry_date(filename)
    if entry_date is None:
        return None

    parsed = ParsedEntry(entry_date=entry_date)
    quality_match = _QUALITY_RE.search(text)
    if quality_match is not None:
        # Strip the field from the prose: entries whose field sat mid-line
        # would otherwise keep raw Dataview syntax in their body.
        text = text[: quality_match.start()] + text[quality_match.end() :]
        raw = quality_match.group(1).strip().lower()
        mapped = _QUALITY_ALIASES.get(raw, raw if raw in _VALID_QUALITIES else None)
        if mapped is None:
            parsed.warnings.append(
                f"{filename}: unrecognised day_quality '{quality_match.group(1)}',"
                " imported without one"
            )
        parsed.day_quality = mapped

    lines = text.splitlines()
    body_start = _prompt_index(lines, _BODY_PROMPT)
    gratitude_start = _prompt_index(lines, _GRATITUDE_PROMPT)

    if body_start is None and gratitude_start is None and quality_match is None:
        # Free prose from before the template, taken whole.
        parsed.body = text.strip() or None
        return parsed

    if body_start is not None:
        parsed.body = _section(lines, body_start + 1)
    else:
        # Templated, but with no How prompt: the leading prose is the body.
        parsed.body = _section(lines, 0)
    if gratitude_start is not None:
        parsed.gratitude = _section(lines, gratitude_start + 1)
    return parsed


def _is_boundary(line: str) -> bool:
    """True for a bold prompt line or any Markdown heading.

    A heading is where the Dataview scaffolding starts, so it ends the
    prose as surely as the next prompt does.
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    return len(stripped) > 4 and stripped.startswith("**") and stripped.endswith("**")


def _prompt_index(lines: list[str], prompt: str) -> int | None:
    """Index of the line carrying a prompt, whatever its asterisk count."""
    for index, line in enumerate(lines):
        if line.strip().strip("*").lower() == prompt:
            return index
    return None


def _section(lines: list[str], start: int) -> str | None:
    """The prose from ``start`` up to the next prompt or heading."""
    collected: list[str] = []
    for line in lines[start:]:
        if _is_boundary(line):
            break
        collected.append(line.rstrip())
    return "\n".join(collected).strip() or None
