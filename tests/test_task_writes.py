"""Unit tests of `services/tasks.py` called with a session, no HTTP.

Covers the status rules shared by create and update as tables of cases: how
`closed_date` follows a status transition, and which writes null the
scheduled fields. Validation of project, parent and profile coherence, and
everything else a request can trigger, is tested through the API in
`test_tasks.py`.
"""

from datetime import date, datetime, time

import pytest
from fastapi import HTTPException

from habit_tracker.constants import TaskStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.services.tasks import add_task, apply_task_update
from tests.factories import ProfileFactory, TaskFactory

OPEN = TaskStatus.OPEN.value
IN_PROGRESS = TaskStatus.IN_PROGRESS.value
SCHEDULED = TaskStatus.SCHEDULED.value
DONE = TaskStatus.DONE.value
CANCELLED = TaskStatus.CANCELLED.value

STORED = datetime(2026, 1, 5, 9, 30)
SUPPLIED = datetime(2026, 2, 10, 17, 0)
NOW = "now"


class TestClosedDateOnUpdate:
    @pytest.mark.parametrize(
        ("initial_status", "data", "expected"),
        [
            pytest.param(OPEN, {"status": DONE}, NOW, id="active-to-closed-stamps"),
            pytest.param(
                IN_PROGRESS, {"status": CANCELLED}, NOW, id="active-to-cancelled"
            ),
            pytest.param(DONE, {"status": OPEN}, None, id="closed-to-active-clears"),
            pytest.param(
                DONE, {"status": CANCELLED}, STORED, id="closed-to-closed-keeps"
            ),
            pytest.param(DONE, {"status": DONE}, STORED, id="same-closed-keeps"),
            pytest.param(
                OPEN,
                {"status": DONE, "closed_date": SUPPLIED},
                SUPPLIED,
                id="closing-honours-supplied",
            ),
            pytest.param(
                DONE,
                {"status": CANCELLED, "closed_date": SUPPLIED},
                SUPPLIED,
                id="closed-to-closed-honours-supplied",
            ),
            pytest.param(
                DONE,
                {"closed_date": SUPPLIED},
                SUPPLIED,
                id="closed-task-corrects-date",
            ),
            pytest.param(DONE, {"title": "Renamed"}, STORED, id="no-status-keeps"),
            pytest.param(OPEN, {"title": "Renamed"}, None, id="active-stays-null"),
        ],
    )
    async def test_transition(self, db_session, initial_status, data, expected):
        profile = ProfileFactory()
        closed_date = STORED if initial_status in (DONE, CANCELLED) else None
        task = TaskFactory(
            profile=profile, status=initial_status, closed_date=closed_date
        )
        await db_session.commit()
        before = utc_now()

        await apply_task_update(db_session, task, profile, dict(data))

        if expected == NOW:
            assert task.closed_date is not None
            assert task.closed_date >= before
        else:
            assert task.closed_date == expected

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({"closed_date": SUPPLIED}, id="active-task"),
            pytest.param(
                {"status": IN_PROGRESS, "closed_date": SUPPLIED}, id="staying-active"
            ),
        ],
    )
    async def test_supplied_on_active_task_raises_422(self, db_session, data):
        profile = ProfileFactory()
        task = TaskFactory(profile=profile, status=OPEN)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await apply_task_update(db_session, task, profile, dict(data))
        assert exc_info.value.status_code == 422
        assert (
            exc_info.value.detail
            == "closed_date can only be set on a done or cancelled task"
        )
        assert task.closed_date is None

    async def test_reopening_with_supplied_date_raises_422(self, db_session):
        profile = ProfileFactory()
        task = TaskFactory(profile=profile, status=DONE, closed_date=STORED)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await apply_task_update(
                db_session, task, profile, {"status": OPEN, "closed_date": SUPPLIED}
            )
        assert exc_info.value.status_code == 422
        assert task.closed_date == STORED


class TestClosedDateOnCreate:
    @pytest.mark.parametrize(
        ("created_status", "stamped"),
        [(OPEN, False), (SCHEDULED, False), (DONE, True), (CANCELLED, True)],
    )
    async def test_closed_status_stamps(self, db_session, created_status, stamped):
        profile = ProfileFactory()
        await db_session.commit()
        before = utc_now()

        task = await add_task(
            db_session,
            {"profile_id": profile.id, "title": "New", "status": created_status},
        )

        if stamped:
            assert task.closed_date is not None
            assert task.closed_date >= before
        else:
            assert task.closed_date is None


SCHEDULED_FIELDS = {"scheduled_date": date(2026, 3, 1), "scheduled_time": time(9, 0)}


class TestScheduledFields:
    @pytest.mark.parametrize(
        ("initial_status", "data", "kept"),
        [
            pytest.param(SCHEDULED, {"title": "Renamed"}, True, id="untouched-kept"),
            pytest.param(SCHEDULED, {"status": OPEN}, False, id="leaving-nulls"),
            pytest.param(
                SCHEDULED, {"status": DONE}, False, id="closing-scheduled-nulls"
            ),
            pytest.param(
                OPEN, {"status": SCHEDULED, **SCHEDULED_FIELDS}, True, id="entering"
            ),
            pytest.param(OPEN, SCHEDULED_FIELDS, False, id="sent-to-active-nulls"),
        ],
    )
    async def test_update(self, db_session, initial_status, data, kept):
        profile = ProfileFactory()
        stored = SCHEDULED_FIELDS if initial_status == SCHEDULED else {}
        task = TaskFactory(profile=profile, status=initial_status, **stored)
        await db_session.commit()

        await apply_task_update(db_session, task, profile, dict(data))

        if kept:
            assert task.scheduled_date == SCHEDULED_FIELDS["scheduled_date"]
            assert task.scheduled_time == SCHEDULED_FIELDS["scheduled_time"]
        else:
            assert task.scheduled_date is None
            assert task.scheduled_time is None

    @pytest.mark.parametrize(
        ("created_status", "kept"), [(SCHEDULED, True), (OPEN, False), (DONE, False)]
    )
    async def test_create(self, db_session, created_status, kept):
        profile = ProfileFactory()
        await db_session.commit()

        task = await add_task(
            db_session,
            {
                "profile_id": profile.id,
                "title": "New",
                "status": created_status,
                **SCHEDULED_FIELDS,
            },
        )

        assert (task.scheduled_date is not None) is kept
        assert (task.scheduled_time is not None) is kept
