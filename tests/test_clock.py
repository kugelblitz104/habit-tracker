"""core/clock.py, and the guard that keeps it the only server-local clock read."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from habit_tracker.core.clock import utc_now

SRC = Path(__file__).resolve().parent.parent / "src" / "habit_tracker"

# The no-argument forms only: datetime.now(UTC), datetime.now(zone) and
# .astimezone(UTC) name their zone and stay legal.
LOCAL_CLOCK = re.compile(
    r"datetime\.now\(\)|default(?:_factory)?=datetime\.now\b(?!\()|\.astimezone\(\)"
)


def test_utc_now_is_naive_utc():
    stamp = utc_now()

    assert stamp.tzinfo is None
    assert abs(datetime.now(UTC).replace(tzinfo=None) - stamp) < timedelta(seconds=5)


def test_no_server_local_clock_reads_outside_core_clock():
    """A server-local read writes a row hours off when the API runs outside
    its UTC container, which is a documented workflow."""
    offenders = [
        f"{path.relative_to(SRC)}:{lineno}: {line.strip()}"
        for path in SRC.rglob("*.py")
        if path.name != "clock.py"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if LOCAL_CLOCK.search(line)
    ]

    assert offenders == []


def test_guard_pattern():
    for bad in (
        "x = datetime.now()",
        "default=datetime.now,",
        "Field(default_factory=datetime.now)",
        "dt.astimezone().replace(tzinfo=None)",
    ):
        assert LOCAL_CLOCK.search(bad), bad
    for ok in (
        "datetime.now(UTC)",
        "datetime.now(zone).date()",
        "default=date.today",
        "default_factory=date.today",
        "default=utc_now",
        "dt.astimezone(UTC)",
    ):
        assert not LOCAL_CLOCK.search(ok), ok
