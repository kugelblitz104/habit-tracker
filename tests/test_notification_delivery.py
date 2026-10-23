"""`fire_due`: claim due rows, apply the fire-time skips, send, advance.

The sender is a recording fake, so nothing touches the network. Profiles are in
America/New_York with every trigger on unless a test says otherwise. Rows are
inserted by hand with a `fire_at` that is a real fire instant of the entity
(`fire_due` treats a row whose instant the entity no longer produces as stale).
"""

import asyncio
import logging
from contextlib import nullcontext
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from habit_tracker.constants import TaskStatus, TrackerStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.schemas.db_models import (
    PushSubscription,
    ScheduledNotification,
    User,
)
from habit_tracker.services import notifications, web_push
from habit_tracker.services.notifications import (
    COUNTDOWN,
    HABIT,
    JOURNAL,
    TASK,
    fire_due,
    next_habit_fire,
    next_journal_fire,
    to_utc,
)
from tests.conftest import engine
from tests.factories import (
    CountdownFactory,
    HabitFactory,
    JournalEntryFactory,
    ProfileFactory,
    TaskFactory,
    TrackerFactory,
    UserFactory,
)

NY = ZoneInfo("America/New_York")
YESTERDAY = date.today() - timedelta(days=1)
JOURNAL_FIRE = to_utc(YESTERDAY, time(20, 0), NY)
HABIT_FIRE = to_utc(YESTERDAY, time(7, 0), NY)


@pytest.fixture(autouse=True)
def _no_late_cutoff(monkeypatch):
    """The fixtures fire rows from yesterday; the late-send cutoff has its own tests."""
    monkeypatch.setitem(notifications.CONFIG["scheduler"], "late_grace_seconds", 10**9)


class Recorder:
    """A fake sender: records (endpoint, payload), answers per-endpoint statuses."""

    def __init__(self, statuses: dict[str, int] | None = None, raises=()):
        self.calls: list[tuple[str, dict]] = []
        self.statuses = statuses or {}
        self.raises = raises

    async def __call__(self, subscription, payload) -> int:
        self.calls.append((subscription.endpoint, payload))
        if subscription.endpoint in self.raises:
            raise RuntimeError("push service unreachable")
        return self.statuses.get(subscription.endpoint, 201)


PROFILE_FIELDS = {
    "timezone": "America/New_York",
    "notify_task_due": True,
    "notify_task_scheduled": True,
    "notify_habits": True,
    "notify_countdowns": True,
    "notify_journal": True,
    "journal_enabled": True,
    "journal_prompt_time": time(20, 0),
}


async def make_profile(db_session, **overrides):
    user = UserFactory(default_profile=False)
    profile = ProfileFactory(user=user, **{**PROFILE_FIELDS, **overrides})
    await db_session.commit()
    return profile


async def subscribe(db_session, profile, endpoint="https://push.example/a"):
    db_session.add(
        PushSubscription(
            profile_id=profile.id, endpoint=endpoint, p256dh="key", auth="secret"
        )
    )
    await db_session.commit()


async def schedule(db_session, profile, entity_type, entity_id, fire_at):
    db_session.add(
        ScheduledNotification(
            profile_id=profile.id,
            entity_type=entity_type,
            entity_id=entity_id,
            fire_at=fire_at,
        )
    )
    await db_session.commit()


async def rows(db_session):
    result = await db_session.execute(select(ScheduledNotification))
    return list(result.scalars())


async def make_due_task(db_session, profile, **fields):
    """A task due yesterday 09:00 with one 60 minute offset, and its due row."""
    task = TaskFactory(
        profile=profile,
        due_date=YESTERDAY,
        due_time=time(9, 0),
        due_reminder_offsets=[60],
        **fields,
    )
    await db_session.commit()
    await schedule(
        db_session, profile, TASK, task.id, to_utc(YESTERDAY, time(8, 0), NY)
    )
    return task


async def make_due_habit(db_session, profile):
    habit = HabitFactory(
        profile=profile, reminder=True, reminder_time=time(7, 0), reminder_days=127
    )
    await db_session.commit()
    await schedule(db_session, profile, HABIT, habit.id, HABIT_FIRE)
    return habit


class TestClaimAndAdvance:
    async def test_sends_a_task_reminder_and_removes_the_spent_row(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        task = await make_due_task(db_session, profile, title="Pay rent")
        send = Recorder()

        sent = await fire_due(db_session, send, utc_now())

        assert sent == 1
        assert send.calls == [
            (
                "https://push.example/a",
                {
                    "title": "Pay rent",
                    "body": "Due in 1 hour",
                    "url": f"/tasks/{task.slug}",
                },
            )
        ]
        # The only offset was 60 minutes before a past anchor: nothing left.
        assert await rows(db_session) == []

    async def test_advances_a_row_that_has_a_next_time(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        now = utc_now()
        send = Recorder()

        await fire_due(db_session, send, now)

        assert send.calls[0][1]["url"] == f"/habits/{habit.slug}"
        assert send.calls[0][1]["title"] == habit.name
        (row,) = await rows(db_session)
        assert row.fire_at == next_habit_fire(habit, profile, now)

    async def test_sends_to_every_subscription_of_the_profile_only(self, db_session):
        profile = await make_profile(db_session)
        other = await make_profile(db_session)
        await subscribe(db_session, profile, "https://push.example/a")
        await subscribe(db_session, profile, "https://push.example/b")
        await subscribe(db_session, other, "https://push.example/elsewhere")
        await make_due_task(db_session, profile)
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert sorted(endpoint for endpoint, _ in send.calls) == [
            "https://push.example/a",
            "https://push.example/b",
        ]

    async def test_rows_not_yet_due_are_left_alone(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        task = TaskFactory(
            profile=profile,
            due_date=date.today() + timedelta(days=30),
            due_time=time(9, 0),
        )
        await db_session.commit()
        later = utc_now() + timedelta(days=29)
        await schedule(db_session, profile, TASK, task.id, later)
        send = Recorder()

        assert await fire_due(db_session, send, utc_now()) == 0

        assert send.calls == []
        assert [r.fire_at for r in await rows(db_session)] == [later]

    async def test_claims_in_batches_until_none_are_left(self, db_session, monkeypatch):
        monkeypatch.setitem(notifications.CONFIG["scheduler"], "claim_batch", 2)
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        for _ in range(5):
            await make_due_task(db_session, profile)
        send = Recorder()

        assert await fire_due(db_session, send, utc_now()) == 5

        assert len(send.calls) == 5
        assert await rows(db_session) == []


class TestFireTimeSkips:
    async def test_habit_completed_that_day_is_skipped_but_advanced(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        TrackerFactory(habit=habit, dated=YESTERDAY, status=TrackerStatus.COMPLETED)
        await db_session.commit()
        now = utc_now()
        send = Recorder()

        assert await fire_due(db_session, send, now) == 0

        assert send.calls == []
        (row,) = await rows(db_session)
        assert row.fire_at == next_habit_fire(habit, profile, now)

    async def test_habit_skipped_that_day_is_not_reminded(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        TrackerFactory(habit=habit, dated=YESTERDAY, status=TrackerStatus.SKIPPED)
        await db_session.commit()
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls == []

    async def test_habit_not_completed_still_fires(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        TrackerFactory(habit=habit, dated=YESTERDAY, status=TrackerStatus.NOT_COMPLETED)
        await db_session.commit()
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert len(send.calls) == 1

    async def test_journal_entry_for_the_day_skips_the_prompt(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        JournalEntryFactory(profile=profile, entry_date=YESTERDAY)
        await db_session.commit()
        await schedule(db_session, profile, JOURNAL, profile.id, JOURNAL_FIRE)
        now = utc_now()
        send = Recorder()

        assert await fire_due(db_session, send, now) == 0

        assert send.calls == []
        (row,) = await rows(db_session)
        assert row.fire_at == next_journal_fire(profile, now)

    async def test_journal_without_an_entry_fires(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        await schedule(db_session, profile, JOURNAL, profile.id, JOURNAL_FIRE)
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls[0][1] == {
            "title": "Journal",
            "body": "Time to journal",
            "url": "/journal",
        }

    async def test_countdown_payload(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        countdown = CountdownFactory(
            profile=profile,
            title="Launch",
            target_date=YESTERDAY,
            target_time=time(9, 0),
            repeat="none",
        )
        await db_session.commit()
        await schedule(
            db_session,
            profile,
            COUNTDOWN,
            countdown.id,
            to_utc(YESTERDAY, time(9, 0), NY),
        )
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls[0][1] == {
            "title": "Launch",
            "body": "Today",
            "url": "/countdown",
        }
        assert await rows(db_session) == []

    async def test_toggle_off_sends_nothing_and_drops_the_stale_row(self, db_session):
        profile = await make_profile(db_session, notify_task_due=False)
        await subscribe(db_session, profile)
        await make_due_task(db_session, profile)
        send = Recorder()

        assert await fire_due(db_session, send, utc_now()) == 0

        assert send.calls == []
        assert await rows(db_session) == []

    async def test_closed_task_sends_nothing(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        await make_due_task(db_session, profile, status=TaskStatus.DONE)
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls == []
        assert await rows(db_session) == []


class TestOrphansAndFailures:
    async def test_row_whose_entity_is_gone_is_deleted_without_sending(
        self, db_session
    ):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        past = utc_now() - timedelta(hours=1)
        for entity_type in (TASK, HABIT, COUNTDOWN):
            await schedule(db_session, profile, entity_type, 999_999, past)
        send = Recorder()

        assert await fire_due(db_session, send, utc_now()) == 0

        assert send.calls == []
        assert await rows(db_session) == []

    async def test_404_and_410_delete_the_subscription(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile, "https://push.example/gone")
        await subscribe(db_session, profile, "https://push.example/missing")
        await subscribe(db_session, profile, "https://push.example/ok")
        await make_due_task(db_session, profile)
        send = Recorder(
            statuses={
                "https://push.example/gone": 410,
                "https://push.example/missing": 404,
            }
        )

        await fire_due(db_session, send, utc_now())

        left = (await db_session.scalars(select(PushSubscription.endpoint))).all()
        assert left == ["https://push.example/ok"]

    async def test_a_disallowed_stored_endpoint_is_deleted_without_a_request(
        self, db_session
    ):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile, "https://internal.example/hook")
        await make_due_task(db_session, profile)
        requests: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(201)

        client = httpx.AsyncClient(transport=httpx.MockTransport(record))

        async def send(subscription, payload):
            return await web_push.send(subscription, payload, client=client)

        await fire_due(db_session, send, utc_now())

        assert requests == []
        assert (await db_session.scalars(select(PushSubscription))).all() == []

    async def test_other_errors_are_logged_and_the_row_still_advances(
        self, db_session, caplog
    ):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile, "https://push.example/500")
        await subscribe(db_session, profile, "https://push.example/boom")
        await subscribe(db_session, profile, "https://push.example/ok")
        await make_due_task(db_session, profile)
        send = Recorder(
            statuses={"https://push.example/500": 500},
            raises={"https://push.example/boom"},
        )

        with caplog.at_level(logging.WARNING):
            await fire_due(db_session, send, utc_now())

        assert len(send.calls) == 3
        assert "answered status 500" in caplog.text
        assert "push service unreachable" in caplog.text
        assert len((await db_session.scalars(select(PushSubscription))).all()) == 3
        assert await rows(db_session) == []

    async def test_subscriptions_come_from_the_entitys_current_profile(
        self, db_session
    ):
        # A row left behind by a project move still names the old profile.
        old = await make_profile(db_session)
        new = await make_profile(db_session)
        await subscribe(db_session, old, "https://push.example/old")
        await subscribe(db_session, new, "https://push.example/new")
        task = TaskFactory(
            profile=new,
            due_date=YESTERDAY,
            due_time=time(9, 0),
            due_reminder_offsets=[60],
        )
        await db_session.commit()
        await schedule(
            db_session, old, TASK, task.id, to_utc(YESTERDAY, time(8, 0), NY)
        )
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert [endpoint for endpoint, _ in send.calls] == ["https://push.example/new"]


@pytest_asyncio.fixture
async def committed(setup_db_schema):
    """Sessions on their own connections whose commits are real, for the tests
    that need two transactions to overlap. Yields the session factory and a
    list to append created user ids to; those users (and everything cascading
    from them) are deleted afterwards."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    user_ids: list[int] = []
    yield factory, user_ids
    async with factory() as cleanup:
        for user_id in user_ids:
            user = await cleanup.get(User, user_id)
            if user:
                await cleanup.delete(user)
        await cleanup.commit()


async def seed_journal_row(factory, user_ids) -> int:
    """A committed profile with one subscription and a journal row due now."""
    async with factory() as setup:
        for f in (UserFactory, ProfileFactory):
            f._meta.sqlalchemy_session = setup  # type: ignore[attr-defined]
        user = UserFactory(default_profile=False)
        profile = ProfileFactory(user=user, **PROFILE_FIELDS)
        await setup.commit()
        user_ids.append(user.id)
        setup.add(
            PushSubscription(
                profile_id=profile.id,
                endpoint="https://push.example/a",
                p256dh="key",
                auth="secret",
            )
        )
        setup.add(
            ScheduledNotification(
                profile_id=profile.id,
                entity_type=JOURNAL,
                entity_id=profile.id,
                fire_at=JOURNAL_FIRE,
            )
        )
        await setup.commit()
        return profile.id


class TestBatchSending:
    async def test_sends_run_concurrently_up_to_the_limit(
        self, db_session, monkeypatch
    ):
        monkeypatch.setitem(notifications.CONFIG["push"], "max_concurrent_sends", 2)
        profile = await make_profile(db_session)
        for n in range(5):
            await subscribe(db_session, profile, f"https://push.example/{n}")
        await make_due_task(db_session, profile)
        running = peak = 0

        async def send(subscription, payload) -> int:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            return 201

        await fire_due(db_session, send, utc_now())

        assert peak == 2

    async def test_a_row_that_raises_is_dropped_and_the_rest_still_send(
        self, db_session, monkeypatch, caplog
    ):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        bad = await make_due_task(db_session, profile, title="bad")
        await make_due_task(db_session, profile, title="good")
        real = notifications._payload

        def payload(entity, profile, fire_at):
            if getattr(entity, "id", None) == bad.id:
                raise ValueError("bad data")
            return real(entity, profile, fire_at)

        monkeypatch.setattr(notifications, "_payload", payload)
        send = Recorder()

        with caplog.at_level(logging.ERROR):
            assert await fire_due(db_session, send, utc_now()) == 1

        assert [call[1]["title"] for call in send.calls] == ["good"]
        assert "bad data" in caplog.text
        assert await rows(db_session) == []


class TestFailedRowRecovery:
    async def test_a_recurring_row_that_raises_once_is_advanced_not_dropped(
        self, db_session, monkeypatch
    ):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        real = notifications._payload
        calls = []

        def payload(entity, profile, fire_at):
            calls.append(fire_at)
            if len(calls) == 1:
                raise ValueError("bad data")
            return real(entity, profile, fire_at)

        monkeypatch.setattr(notifications, "_payload", payload)
        now = utc_now()

        assert await fire_due(db_session, Recorder(), now) == 0

        (row,) = await rows(db_session)
        assert row.fire_at == next_habit_fire(habit, profile, now)

    async def test_a_row_whose_entity_is_gone_is_deleted(self, db_session):
        profile = await make_profile(db_session)
        await schedule(db_session, profile, HABIT, 999999, HABIT_FIRE)

        await fire_due(db_session, Recorder(), utc_now())

        assert await rows(db_session) == []


class TestLateSends:
    async def test_a_row_past_the_grace_period_advances_without_sending(
        self, db_session, monkeypatch
    ):
        monkeypatch.setitem(
            notifications.CONFIG["scheduler"], "late_grace_seconds", 3600
        )
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        now = HABIT_FIRE + timedelta(hours=2)
        send = Recorder()

        assert await fire_due(db_session, send, now) == 0

        assert send.calls == []
        (row,) = await rows(db_session)
        assert row.fire_at == next_habit_fire(habit, profile, now)

    async def test_a_row_inside_the_grace_period_sends(self, db_session, monkeypatch):
        monkeypatch.setitem(
            notifications.CONFIG["scheduler"], "late_grace_seconds", 3600
        )
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        await make_due_habit(db_session, profile)
        send = Recorder()

        sent = await fire_due(db_session, send, HABIT_FIRE + timedelta(minutes=30))

        assert sent == 1


class TestDeliveredCount:
    async def test_no_subscriptions_counts_as_not_sent(self, db_session):
        profile = await make_profile(db_session)
        await make_due_task(db_session, profile)

        assert await fire_due(db_session, Recorder(), utc_now()) == 0
        assert await rows(db_session) == []

    async def test_every_send_failing_counts_as_not_sent(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile, "https://push.example/500")
        await subscribe(db_session, profile, "https://push.example/boom")
        await make_due_task(db_session, profile)
        send = Recorder(
            statuses={"https://push.example/500": 500},
            raises={"https://push.example/boom"},
        )

        assert await fire_due(db_session, send, utc_now()) == 0

    async def test_one_good_subscription_counts_the_row(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile, "https://push.example/500")
        await subscribe(db_session, profile, "https://push.example/ok")
        await make_due_task(db_session, profile)
        send = Recorder(statuses={"https://push.example/500": 500})

        assert await fire_due(db_session, send, utc_now()) == 1


class TestPayloadText:
    async def test_title_and_body_are_clipped(self, db_session, monkeypatch):
        config = notifications.CONFIG["push"]
        monkeypatch.setitem(config, "max_title_chars", 10)
        monkeypatch.setitem(config, "max_body_chars", 8)
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        await make_due_task(db_session, profile, title="x" * 50)
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        payload = send.calls[0][1]
        assert payload["title"] == "x" * 9 + "\u2026"
        assert len(payload["body"]) == 8

    async def test_habit_body_is_its_question(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        habit.question = "Did you stretch?"
        await db_session.commit()
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls[0][1]["body"] == "Did you stretch?"

    async def test_blank_habit_question_falls_back(self, db_session):
        profile = await make_profile(db_session)
        await subscribe(db_session, profile)
        habit = await make_due_habit(db_session, profile)
        habit.question = "  "
        await db_session.commit()
        send = Recorder()

        await fire_due(db_session, send, utc_now())

        assert send.calls[0][1]["body"] == "Time to check in"


class TestConcurrency:
    async def test_two_workers_send_once(self, committed):
        """The first worker holds its claim open while the second runs; SKIP
        LOCKED makes the second see nothing, so the reminder goes out once."""
        factory, user_ids = committed
        await seed_journal_row(factory, user_ids)
        first_sending = asyncio.Event()
        release = asyncio.Event()
        sent: list[str] = []

        async def slow_send(subscription, payload) -> int:
            sent.append("first")
            first_sending.set()
            await release.wait()
            return 201

        async def fast_send(subscription, payload) -> int:
            sent.append("second")
            return 201

        async def worker(send) -> int:
            async with factory() as db:
                return await fire_due(db, send, utc_now())

        first = asyncio.create_task(worker(slow_send))
        try:
            await asyncio.wait_for(first_sending.wait(), timeout=10)
            second_count = await asyncio.wait_for(worker(fast_send), timeout=10)
        finally:
            release.set()
        first_count = await asyncio.wait_for(first, timeout=10)

        assert (first_count, second_count) == (1, 0)
        assert sent == ["first"]


async def wait_for(condition, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.02)


class TestRun:
    async def test_run_fires_what_is_due_then_wakes_on_a_poke(self, committed):
        factory, user_ids = committed
        profile_id = await seed_journal_row(factory, user_ids)
        sent: list[str] = []

        async def send(subscription, payload) -> int:
            sent.append(payload["title"])
            return 201

        loop_task = asyncio.create_task(notifications.run(factory, send))
        try:
            await wait_for(lambda: len(sent) == 1)

            # The journal row advanced to tomorrow. Move it back and poke: the
            # loop must wake now rather than sleep until tomorrow's prompt.
            async with factory() as db:
                await db.execute(
                    update(ScheduledNotification)
                    .where(ScheduledNotification.entity_id == profile_id)
                    .values(fire_at=JOURNAL_FIRE)
                )
                await db.commit()
            notifications.poke(JOURNAL_FIRE)
            await wait_for(lambda: len(sent) == 2)
        finally:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)

    async def test_run_survives_a_failing_pass(self, monkeypatch):
        calls = 0

        async def boom(db, send, now):
            nonlocal calls
            calls += 1
            raise RuntimeError("database hiccup")

        monkeypatch.setattr(notifications, "fire_due", boom)
        loop_task = asyncio.create_task(
            notifications.run(
                lambda: nullcontext(None),  # pyright: ignore[reportArgumentType]
                Recorder(),
            )
        )
        try:
            await wait_for(lambda: calls == 1)
            notifications.poke(utc_now() - timedelta(hours=1))
            await wait_for(lambda: calls == 2)
        finally:
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)

    async def test_a_failed_pass_sleeps_the_error_backoff(self, monkeypatch):
        monkeypatch.setitem(
            notifications.CONFIG["scheduler"], "error_backoff_seconds", 7
        )

        async def boom(db, send, now):
            raise RuntimeError("database hiccup")

        delays: list[float] = []

        async def fake_wait_for(awaitable, delay):
            delays.append(delay)
            awaitable.close()
            raise asyncio.CancelledError

        monkeypatch.setattr(notifications, "fire_due", boom)
        monkeypatch.setattr(notifications.asyncio, "wait_for", fake_wait_for)

        with pytest.raises(asyncio.CancelledError):
            await notifications.run(
                lambda: nullcontext(None),  # pyright: ignore[reportArgumentType]
                Recorder(),
            )

        assert delays == [pytest.approx(7, abs=0.5)]


class TestLifespan:
    async def _run_lifespan(
        self, monkeypatch, vapid_key: str, subject: str = "mailto:ops@example.com"
    ) -> list[object]:
        from habit_tracker.core.config import settings
        from habit_tracker.main import app

        started: list[object] = []

        async def fake_run(session_factory, send):
            started.append(send)
            await asyncio.Event().wait()

        monkeypatch.setattr(settings, "vapid_private_key", vapid_key)
        monkeypatch.setattr(settings, "vapid_subject", subject)
        monkeypatch.setattr(notifications, "run", fake_run)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)
        return started

    async def test_the_loop_starts_when_vapid_is_configured(self, monkeypatch):
        started = await self._run_lifespan(monkeypatch, "configured")

        assert len(started) == 1

    async def test_the_loop_stays_off_without_vapid(self, monkeypatch):
        assert await self._run_lifespan(monkeypatch, "") == []

    async def test_a_key_without_a_subject_stays_off_and_warns(
        self, monkeypatch, caplog
    ):
        with caplog.at_level(logging.WARNING):
            assert await self._run_lifespan(monkeypatch, "configured", "") == []

        assert "VAPID_SUBJECT" in caplog.text
