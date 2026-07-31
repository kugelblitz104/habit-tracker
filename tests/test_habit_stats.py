"""Unit tests for the pure KPI math in ``services.habit_stats``.

These build Habit/Tracker instances in memory - no session, no API - so the
arithmetic can be pinned down exactly.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from habit_tracker.constants import TrackerStatus
from habit_tracker.schemas.db_models import Habit, Tracker
from habit_tracker.services.habit_stats import (
    calculate_kpis,
    calculate_streaks,
    get_effective_start_date,
)

# A clean 4-week window: Mon 2026-01-05 through Sun 2026-02-01 gives exactly
# four of every weekday, so a weekday's completed share lands on a round 0.25.
START = date(2026, 1, 5)
TODAY = date(2026, 2, 1)

MON, TUE, WED, THU = 0, 1, 2, 3


def _habit(
    frequency: int, range_: int, created_date: datetime = datetime(2026, 1, 5)
) -> Habit:
    return Habit(
        id=1,
        profile_id=1,
        name="Test",
        question="Did you?",
        color="#ffffff",
        frequency=frequency,
        range=range_,
        created_date=created_date,
    )


def _tracker(day: date, status: int = TrackerStatus.COMPLETED) -> Tracker:
    return Tracker(id=int(day.strftime("%m%d")), habit_id=1, dated=day, status=status)


def _weekday_rates(habit: Habit, trackers: list[Tracker]) -> list[float]:
    return calculate_kpis(habit, trackers, TODAY).weekday_completion_rates


def test_weekday_rate_is_completed_share_not_goal_normalized():
    """A weekday's rate is completed/occurrences, NOT completed/expected.

    Normalizing by ``frequency / range`` scales every bar by ``range /
    frequency`` (7x here) and saturates at 1.0, which made a single stray
    Monday render as tall as a Wednesday completed every single week.
    """
    habit = _habit(frequency=1, range_=7)
    trackers = [
        _tracker(date(2026, 1, 7)),  # every Wednesday
        _tracker(date(2026, 1, 14)),
        _tracker(date(2026, 1, 21)),
        _tracker(date(2026, 1, 28)),
        _tracker(date(2026, 1, 5)),  # one stray Monday
    ]

    rates = _weekday_rates(habit, trackers)

    assert rates[WED] == 1.0  # 4 of 4
    assert rates[MON] == 0.25  # 1 of 4 - would be 1.0 under goal-normalization


def test_weekday_rate_ignores_skipped_and_auto_skipped_days():
    """Only COMPLETED counts. Explicit skips and auto-skips contribute zero.

    With frequency=1/range=7, the Wednesday completions auto-skip the rest of
    each week - those days must not inflate their weekday's bar.
    """
    habit = _habit(frequency=1, range_=7)
    trackers = [
        _tracker(date(2026, 1, 7)),  # Wednesdays: completed
        _tracker(date(2026, 1, 14)),
        _tracker(date(2026, 1, 21)),
        _tracker(date(2026, 1, 28)),
        _tracker(date(2026, 1, 6), TrackerStatus.SKIPPED),  # a Tuesday
        _tracker(date(2026, 1, 13), TrackerStatus.SKIPPED),
    ]

    rates = _weekday_rates(habit, trackers)

    assert rates[TUE] == 0.0  # explicitly skipped
    assert rates[THU] == 0.0  # auto-skipped by Wednesday's completion
    assert rates[WED] == 1.0


def test_weekday_rates_are_zero_without_trackers():
    rates = _weekday_rates(_habit(frequency=1, range_=1), [])

    assert rates == [0.0] * 7


def test_daily_habit_weekday_rates_are_plain_completion_share():
    """frequency == range (daily): the share is unaffected by normalization."""
    habit = _habit(frequency=1, range_=1)
    trackers = [_tracker(date(2026, 1, 5)), _tracker(date(2026, 1, 12))]

    rates = _weekday_rates(habit, trackers)

    assert rates[MON] == 0.5  # 2 of 4 Mondays
    assert rates[TUE] == 0.0


# --------------------------------------------------------------------------- #
# Cross-repo parity with the frontend
# --------------------------------------------------------------------------- #
#
# The frontend re-implements this module in
# ``src/features/trackers/utils/kpi-utils.ts`` + ``kpi-adapter.ts`` so a habit
# toggle can patch its ``['kpis']`` / ``['streaks']`` caches optimistically.
# Both repos run the SAME committed table of cases, so a change to either
# implementation without the other turns one of the two suites red.
#
# The case file is canonical in the FRONTEND repo. Point KPI_PARITY_CASES at it
# if the sibling checkout lives somewhere else; without the file these tests
# SKIP loudly rather than pass, because a silent pass would read as "parity
# verified" when nothing was compared.
#
# ``expected`` holds quantities the two sides agree on; ``divergent`` holds ones
# they don't, and each side asserts its OWN recorded value so the disagreement
# is pinned instead of papered over. See ``_divergences`` in the JSON. When a
# divergence is fixed, move the quantity from ``divergent`` into ``expected``.
#
# Every case carries an explicit ``anchor_date`` passed straight in as ``today``
# - nothing here reads ``date.today()``.

_PARITY_ENV_VAR = "KPI_PARITY_CASES"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PARITY_PATH = (
    _REPO_ROOT.parent
    / "habit-tracker-front-end"
    / "src"
    / "test-support"
    / "kpi-parity-cases.json"
)
_PARITY_PATH = Path(os.environ.get(_PARITY_ENV_VAR) or _DEFAULT_PARITY_PATH)

_SKIP_REASON = (
    f"Cross-repo KPI parity cases not found at {_PARITY_PATH}. The file is "
    f"canonical in the frontend repo at "
    f"habit-tracker-front-end/src/test-support/kpi-parity-cases.json - check that "
    f"repo out beside this one, or set {_PARITY_ENV_VAR} to the file's path. "
    f"Skipping means frontend/backend KPI parity is UNVERIFIED, not verified."
)

# Every quantity a case must pin, across `expected` + `divergent`.
_QUANTITY_KEYS = frozenset(
    {
        "effective_start_date",
        "total_completions",
        "current_streak",
        "longest_streak",
        "longest_streak_end_date",
        "overall_completion_rate",
        "thirty_day_completion_rate",
        "last_completed_date",
        "weekday_completion_rates",
        "streaks",
    }
)

# Rates are compared with a tolerance; everything else is exact.
_FLOAT_KEYS = frozenset(
    {
        "overall_completion_rate",
        "thirty_day_completion_rate",
        "weekday_completion_rates",
    }
)


def _load_parity_doc() -> dict:
    if not _PARITY_PATH.is_file():
        return {"_divergences": {}, "cases": []}
    return json.loads(_PARITY_PATH.read_text(encoding="utf-8"))


_PARITY_DOC = _load_parity_doc()
_PARITY_CASES: list[dict] = _PARITY_DOC["cases"]

if _PARITY_CASES:
    _PARITY_PARAMS = [pytest.param(c, id=c["name"]) for c in _PARITY_CASES]
else:
    _PARITY_PARAMS = [
        pytest.param(
            None,
            id="parity-cases-file-missing",
            marks=pytest.mark.skip(reason=_SKIP_REASON),
        )
    ]


def _parity_quantities(case: dict) -> dict:
    """Run every shared quantity for one case, keyed by the server's names."""
    spec = case["habit"]
    habit = _habit(
        frequency=spec["frequency"],
        range_=spec["range"],
        created_date=datetime.fromisoformat(spec["created_date"]),
    )
    # Transient ORM rows take no INSERT-time defaults, so `dated` and `status`
    # are always set explicitly - they are all the math reads off a tracker.
    trackers = [
        _tracker(date.fromisoformat(t["dated"]), t["status"]) for t in case["trackers"]
    ]
    today = date.fromisoformat(case["anchor_date"])

    kpis = calculate_kpis(habit, trackers, today)
    streaks = calculate_streaks(
        trackers, habit.frequency, habit.range, habit.created_date, today
    )
    start = get_effective_start_date(trackers, habit.created_date)

    return {
        "effective_start_date": start.isoformat(),
        "total_completions": kpis.total_completions,
        "current_streak": kpis.current_streak,
        "longest_streak": kpis.longest_streak,
        "longest_streak_end_date": (
            kpis.longest_streak_end_date.isoformat()
            if kpis.longest_streak_end_date is not None
            else None
        ),
        "overall_completion_rate": kpis.overall_completion_rate,
        "thirty_day_completion_rate": kpis.thirty_day_completion_rate,
        "last_completed_date": (
            kpis.last_completed_date.isoformat()
            if kpis.last_completed_date is not None
            else None
        ),
        "weekday_completion_rates": kpis.weekday_completion_rates,
        "streaks": [
            {
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "length": s.length,
            }
            for s in streaks
        ],
    }


@pytest.mark.parametrize("case", _PARITY_PARAMS)
def test_kpi_parity_with_frontend(case: dict):
    """Backend KPIs match the shared cross-repo case table."""
    actual = _parity_quantities(case)

    wanted: dict[str, object] = dict(case["expected"])
    bugs: dict[str, list[str]] = {}
    for key, divergence in case.get("divergent", {}).items():
        wanted[key] = divergence["backend"]
        bugs[key] = divergence["bugs"]

    assert set(wanted) == _QUANTITY_KEYS, (
        f"{case['name']}: a parity case must pin every shared quantity exactly "
        f"once across `expected` and `divergent`; "
        f"missing {sorted(_QUANTITY_KEYS - set(wanted))}, "
        f"unknown {sorted(set(wanted) - _QUANTITY_KEYS)}"
    )

    for key, want in wanted.items():
        note = f" [known divergence: {', '.join(bugs[key])}]" if key in bugs else ""
        if key in _FLOAT_KEYS:
            assert actual[key] == pytest.approx(want, abs=1e-12), f"{key}{note}"
        else:
            assert actual[key] == want, f"{key}{note}"


@pytest.mark.skipif(not _PARITY_CASES, reason=_SKIP_REASON)
def test_parity_cases_only_cite_documented_divergences():
    """Every `bugs` entry resolves to an explanation in `_divergences`."""
    documented = set(_PARITY_DOC["_divergences"])

    for case in _PARITY_CASES:
        for key, divergence in case.get("divergent", {}).items():
            assert divergence["bugs"], f"{case['name']} / {key} names no defect"
            unknown = set(divergence["bugs"]) - documented
            assert not unknown, (
                f"{case['name']} / {key} cites undocumented divergence(s) "
                f"{sorted(unknown)}; add them to `_divergences` in {_PARITY_PATH.name}"
            )
