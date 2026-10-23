"""Cross-repo parity for countdown recurrence.

``services.notifications.next_occurrence`` re-implements the front-end's
``nextOccurrence`` (features/countdowns/utils/countdown.ts), because the server
now has to know when a repeating countdown next fires. Both repos run the same
committed table, canonical in the FRONT-END repo at
``src/test-support/countdown-occurrence-cases.json``, so a change to either side
without the other turns one suite red.

Point COUNTDOWN_PARITY_CASES at the file if the sibling checkout lives
elsewhere. Without it these tests SKIP loudly: a skip means parity is
unverified, not verified.
"""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from habit_tracker.services.notifications import next_occurrence

_ENV_VAR = "COUNTDOWN_PARITY_CASES"
_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2]
    / "habit-tracker-front-end"
    / "src"
    / "test-support"
    / "countdown-occurrence-cases.json"
)
_PATH = Path(os.environ.get(_ENV_VAR) or _DEFAULT_PATH)

_SKIP_REASON = (
    f"Countdown parity cases not found at {_PATH}. The file is canonical in the "
    f"front-end repo at habit-tracker-front-end/src/test-support/"
    f"countdown-occurrence-cases.json - check that repo out beside this one, or "
    f"set {_ENV_VAR} to its path. Skipping means countdown recurrence parity is "
    f"UNVERIFIED, not verified."
)

if _PATH.is_file():
    _CASES = json.loads(_PATH.read_text(encoding="utf-8"))["cases"]
    _PARAMS = [pytest.param(c, id=c["name"]) for c in _CASES]
else:
    _PARAMS = [pytest.param(None, marks=pytest.mark.skip(reason=_SKIP_REASON))]


@pytest.mark.parametrize("case", _PARAMS)
def test_next_occurrence_matches_the_shared_table(case):
    result = next_occurrence(
        date.fromisoformat(case["anchor"]),
        case["repeat"],
        date.fromisoformat(case["on_or_after"]),
    )

    assert result.isoformat() == case["expected"]
