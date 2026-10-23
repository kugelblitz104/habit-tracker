"""Web Push reminders: when each entity next fires, and the loop that sends them.

There are five triggers, each switched on per profile: a task's due date, a
task's scheduled date, a habit's reminder, a countdown reaching its target
(repeats included) and the daily journal prompt.

The schedule is one `ScheduledNotification` row per entity, holding the next
instant it fires. `next_fire` computes that instant from the entity alone, and
it is called from exactly two places: `reschedule` (after a write that could
move it) and `fire_due` (after a send, to advance). Nothing else sets
`fire_at`, which is what keeps the table a pure function of the entities: any
row can be thrown away and recomputed.

Wall-clock rules ("09:00 on weekdays", "1 day before") are evaluated in the
profile's IANA zone and only then converted to naive UTC. Python's arithmetic
on a zone-aware datetime is wall-clock arithmetic, so "1 day before 09:00" is
09:00 the day before even when a DST change falls in between.
"""

import asyncio
import logging
import tomllib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, event, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from habit_tracker.constants import CLOSED_STATUSES, TrackerStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.schemas.db_models import (
    Countdown,
    Habit,
    JournalEntry,
    Profile,
    PushSubscription,
    ScheduledNotification,
    Task,
    Tracker,
)

logger = logging.getLogger(__name__)

# Web Push tunables, one dict per [section] of core/notifications.toml.
with (Path(__file__).parent.parent / "core" / "notifications.toml").open("rb") as _f:
    CONFIG = tomllib.load(_f)

TASK = "task"
HABIT = "habit"
COUNTDOWN = "countdown"
# The journal reminder belongs to the profile itself.
JOURNAL = "profile"

_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 24 * _MINUTES_PER_HOUR
_MINUTES_PER_WEEK = 7 * _MINUTES_PER_DAY


def to_utc(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The naive-UTC instant of a local wall-clock `day` + `at` in `zone`."""
    local = datetime.combine(day, at, tzinfo=zone)
    return local.astimezone(UTC).replace(tzinfo=None)


def _zone(profile: Profile) -> ZoneInfo | None:
    """The profile's zone, or None until the client has reported one.

    A zone this server cannot construct (a restored backup is not validated)
    counts as none: that profile never fires, and the rest of the schedule is
    unaffected.
    """
    if profile.timezone is None:
        return None
    try:
        return ZoneInfo(profile.timezone)
    except (KeyError, ValueError, OSError):
        return None


def _local_today(now: datetime, zone: ZoneInfo) -> date:
    """The calendar day it is in `zone` at naive-UTC `now`."""
    return now.replace(tzinfo=UTC).astimezone(zone).date()


def task_fire_times(
    task: Task, profile: Profile
) -> dict[datetime, list[tuple[str, int]]]:
    """Every instant a task reminds at, each mapped to what produced it.

    The keys are naive-UTC instants; each value lists the `("due" |
    "scheduled", offset_minutes)` pairs that land on that instant. Two dates
    producing the same instant share one key, which is what makes a coincident
    due and scheduled reminder a single notification.

    A date's offsets are the task's own list when it has one, else the
    profile's default. A date-only task counts from the profile's default time
    of day. The profile toggle for a date overrides everything, custom offsets
    included.
    """
    zone = _zone(profile)
    if zone is None or task.status in CLOSED_STATUSES:
        return {}

    anchors = [
        (
            "due",
            profile.notify_task_due,
            task.due_date,
            task.due_time,
            task.due_reminder_offsets,
            profile.task_due_reminder_offsets,
        ),
        (
            "scheduled",
            profile.notify_task_scheduled,
            task.scheduled_date,
            task.scheduled_time,
            task.scheduled_reminder_offsets,
            profile.task_scheduled_reminder_offsets,
        ),
    ]
    times: dict[datetime, list[tuple[str, int]]] = defaultdict(list)
    for name, enabled, day, at, own, default in anchors:
        if not enabled or day is None:
            continue
        offsets = own if own is not None else default
        local = datetime.combine(
            day, at or profile.task_reminder_default_time, tzinfo=zone
        )
        for offset in offsets:
            fire = (local - timedelta(minutes=offset)).astimezone(UTC)
            times[fire.replace(tzinfo=None)].append((name, offset))
    return dict(times)


def next_task_fire(task: Task, profile: Profile, now: datetime) -> datetime | None:
    """The task's earliest reminder strictly after `now`, or None.

    Reminders already behind `now` are dropped rather than sent late, so a
    task created 30 minutes before it is due gets only its 15-minute reminder,
    and reminders missed while the API was down collapse into the one claim
    that catches up on them.
    """
    upcoming = [t for t in task_fire_times(task, profile) if t > now]
    return min(upcoming, default=None)


def offset_label(minutes: int) -> str:
    """An offset in the largest unit that divides it evenly ("1 day", "90 min")."""
    if minutes == 0:
        return "now"
    for size, unit in (
        (_MINUTES_PER_WEEK, "week"),
        (_MINUTES_PER_DAY, "day"),
        (_MINUTES_PER_HOUR, "hour"),
    ):
        if minutes % size == 0:
            count = minutes // size
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    return f"{minutes} min"


def _relative(minutes: int) -> str:
    """ "now" for a zero offset, else "in <offset>"."""
    label = offset_label(minutes)
    return label if minutes == 0 else f"in {label}"


def task_body(task: Task, profile: Profile, fire_at: datetime) -> str:
    """The notification text for a task reminder firing at `fire_at`.

    Worked out from the task at send time rather than stored with the row:
    "Due in 15 min", "Scheduled in 1 hour", "Due and scheduled in 15 min" when
    both dates land here with the same offset, else "Due in 1 day, scheduled
    now".
    """
    sources = task_fire_times(task, profile).get(fire_at, [])
    if not sources:
        return "Reminder"
    offsets = {offset for _, offset in sources}
    if len(sources) > 1 and len(offsets) == 1:
        text = f"due and scheduled {_relative(offsets.pop())}"
    else:
        text = ", ".join(f"{name} {_relative(offset)}" for name, offset in sources)
    return text[0].upper() + text[1:]


def next_habit_fire(habit: Habit, profile: Profile, now: datetime) -> datetime | None:
    """The habit's next `reminder_time` on a day its `reminder_days` mask allows.

    The mask is bit 0 = Monday ... bit 6 = Sunday. Looks at most a week ahead,
    which always finds the next allowed day when the mask has any bit set.
    """
    zone = _zone(profile)
    if (
        zone is None
        or not profile.notify_habits
        or not habit.reminder
        or habit.reminder_time is None
        or habit.archived
    ):
        return None
    today = _local_today(now, zone)
    for ahead in range(8):
        day = today + timedelta(days=ahead)
        if not habit.reminder_days & (1 << day.weekday()):
            continue
        fire = to_utc(day, habit.reminder_time, zone)
        if fire > now:
            return fire
    return None


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _clamped(year: int, month: int, day: int) -> date:
    """`day` of the month, clamped to its last day (31 -> 28 in February)."""
    return date(year, month, min(day, _last_day_of_month(year, month)))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    """The `ordinal`-th `weekday` (0 = Monday) of a month; 5 means the last one."""
    if ordinal >= 5:
        last = date(year, month, _last_day_of_month(year, month))
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (ordinal - 1) * 7)


def next_occurrence(anchor: date, repeat: str, on_or_after: date) -> date:
    """A countdown's next occurrence on or after `on_or_after`.

    The Python twin of the front-end's `nextOccurrence`
    (features/countdowns/utils/countdown.ts); the shared case table in
    test_countdown_occurrence.py keeps the two in step. `anchor` is the
    countdown's stored `target_date`. A non-recurring countdown, or one whose
    anchor has not arrived yet, returns the anchor itself.

    - weekly: the anchor plus whole weeks.
    - monthly: the anchor's day of month, clamped to shorter months.
    - yearly: the anchor's month and day, clamped (29 Feb -> 28 Feb).
    - monthly_weekday: the anchor's weekday and its ordinal in the month
      (3rd Monday); an anchor in the month's last seven days counts as 5th,
      meaning "the last one".
    """
    if repeat == "none" or anchor >= on_or_after:
        return anchor

    if repeat == "weekly":
        weeks = -(-(on_or_after - anchor).days // 7)
        return anchor + timedelta(weeks=weeks)

    year, month = on_or_after.year, on_or_after.month
    if repeat == "monthly":
        candidate = _clamped(year, month, anchor.day)
        if candidate < on_or_after:
            candidate = _clamped(*_next_month(year, month), anchor.day)
        return candidate

    if repeat == "yearly":
        candidate = _clamped(year, anchor.month, anchor.day)
        if candidate < on_or_after:
            candidate = _clamped(year + 1, anchor.month, anchor.day)
        return candidate

    if repeat == "monthly_weekday":
        weekday = anchor.weekday()
        ordinal = (anchor.day - 1) // 7 + 1
        candidate = _nth_weekday(year, month, weekday, ordinal)
        if candidate < on_or_after:
            candidate = _nth_weekday(*_next_month(year, month), weekday, ordinal)
        return candidate

    return anchor


def next_countdown_fire(
    countdown: Countdown, profile: Profile, now: datetime
) -> datetime | None:
    """When a countdown next reaches its target: its `target_time`, else the
    profile's default time, on its next occurrence. None for an archived
    countdown or a one-time countdown already past."""
    zone = _zone(profile)
    if zone is None or not profile.notify_countdowns or countdown.archived_date:
        return None
    at = countdown.target_time or profile.task_reminder_default_time
    today = _local_today(now, zone)
    day = next_occurrence(countdown.target_date, countdown.repeat, today)
    fire = to_utc(day, at, zone)
    if fire > now:
        return fire
    if countdown.repeat == "none":
        return None
    # Today's occurrence has already fired; take the one after it.
    day = next_occurrence(countdown.target_date, countdown.repeat, today + timedelta(1))
    return to_utc(day, at, zone)


def next_journal_fire(profile: Profile, now: datetime) -> datetime | None:
    """The next `journal_prompt_time`: today's if still ahead, else tomorrow's."""
    zone = _zone(profile)
    at = profile.journal_prompt_time
    if (
        zone is None
        or not profile.notify_journal
        or not profile.journal_enabled
        or at is None
    ):
        return None
    today = _local_today(now, zone)
    fire = to_utc(today, at, zone)
    if fire > now:
        return fire
    return to_utc(today + timedelta(days=1), at, zone)


def next_fire(
    entity_type: str,
    entity: Task | Habit | Countdown | Profile,
    profile: Profile,
    now: datetime,
) -> datetime | None:
    """The entity's next fire instant strictly after `now`, or None.

    `entity` is the profile itself for the journal reminder. A date the
    calendar cannot represent (a task due 9999-12-31, a yearly countdown whose
    next occurrence is year 10000) has no next fire time; it must not fail the
    write that stored it.
    """
    if entity_type not in (TASK, HABIT, COUNTDOWN, JOURNAL):
        raise ValueError(f"Unknown notification entity type: {entity_type!r}")
    try:
        if entity_type == TASK:
            return next_task_fire(entity, profile, now)  # type: ignore[arg-type]
        if entity_type == HABIT:
            return next_habit_fire(entity, profile, now)  # type: ignore[arg-type]
        if entity_type == COUNTDOWN:
            return next_countdown_fire(entity, profile, now)  # type: ignore[arg-type]
        return next_journal_fire(profile, now)
    except (OverflowError, ValueError):
        return None


# The earliest fire time the loop knows about, and the event that wakes it. A
# write that moves a fire time earlier than `_next_at` lowers it and sets the
# event; a later or deleted time changes nothing, because the loop wakes at the
# old time, finds nothing due and re-reads the schedule. Process-local, which
# is correct for the single API process; a second replica would still catch
# up within `max_sleep_seconds`.
_next_at: datetime | None = None
_wake = asyncio.Event()


def poke(fire_at: datetime) -> None:
    """Tell the loop a row now fires at `fire_at`; wakes it only if earlier."""
    global _next_at
    if _next_at is None or fire_at < _next_at:
        _next_at = fire_at
        _wake.set()


# Key in `Session.info` holding the earliest fire time written by the open
# transaction. Poking before the commit would wake the loop for a row it
# cannot see yet, or for one a rollback removes.
_PENDING = "notification_fire_at"


@event.listens_for(Session, "after_commit")
def _poke_after_commit(session: Session) -> None:
    fire_at = session.info.pop(_PENDING, None)
    if fire_at is not None:
        poke(fire_at)


@event.listens_for(Session, "after_rollback")
def _discard_pending_poke(session: Session) -> None:
    session.info.pop(_PENDING, None)


def _poke_on_commit(db: AsyncSession, fire_at: datetime) -> None:
    pending = db.sync_session.info.get(_PENDING)
    if pending is None or fire_at < pending:
        db.sync_session.info[_PENDING] = fire_at


def _upsert(rows: list[dict]):
    """INSERT ... ON CONFLICT on the one-row-per-entity constraint, which moves
    an existing row to the new profile and time."""
    stmt = insert(ScheduledNotification).values(rows)
    return stmt.on_conflict_do_update(
        constraint="uq_scheduled_notification_entity",
        set_={"profile_id": stmt.excluded.profile_id, "fire_at": stmt.excluded.fire_at},
    )


async def reschedule(
    db: AsyncSession, entity_type: str, entity: Task | Habit | Countdown
) -> None:
    """Recompute one entity's schedule row inside the caller's transaction.

    Call it after every write that could move the entity's fire time, before
    the commit. It upserts the row, or deletes it when nothing is left to fire,
    and arranges for the loop to be woken once the transaction commits.
    """
    if entity.id is None:
        await db.flush()
    profile = await db.get(Profile, entity.profile_id)
    fire_at = next_fire(entity_type, entity, profile, utc_now()) if profile else None
    if fire_at is None:
        await forget(db, entity_type, entity.id)
        return
    await db.execute(
        _upsert(
            [
                {
                    "profile_id": entity.profile_id,
                    "entity_type": entity_type,
                    "entity_id": entity.id,
                    "fire_at": fire_at,
                }
            ]
        )
    )
    _poke_on_commit(db, fire_at)


async def forget(db: AsyncSession, entity_type: str, entity_id: int) -> None:
    """Drop an entity's schedule row (a deleted entity, or one with nothing to fire)."""
    await db.execute(
        delete(ScheduledNotification).where(
            ScheduledNotification.entity_type == entity_type,
            ScheduledNotification.entity_id == entity_id,
        )
    )


async def reschedule_profile(db: AsyncSession, profile: Profile) -> None:
    """Rebuild every schedule row of one profile.

    For a change that can move many rows at once: a toggle, offsets, default
    time, timezone or journal setting, a project move, or a backup import. The
    profile's rows are deleted and rewritten from the entities, which also
    sweeps rows whose entity has gone.
    """
    await db.flush()
    now = utc_now()
    tasks = await db.scalars(
        select(Task).where(
            Task.profile_id == profile.id,
            Task.status.notin_(CLOSED_STATUSES),
            or_(Task.due_date.is_not(None), Task.scheduled_date.is_not(None)),
        )
    )
    habits = await db.scalars(
        select(Habit).where(Habit.profile_id == profile.id, Habit.reminder.is_(True))
    )
    countdowns = await db.scalars(
        select(Countdown).where(
            Countdown.profile_id == profile.id, Countdown.archived_date.is_(None)
        )
    )
    candidates: list[tuple[str, int, datetime | None]] = [
        (TASK, t.id, next_fire(TASK, t, profile, now)) for t in tasks
    ]
    candidates += [(HABIT, h.id, next_fire(HABIT, h, profile, now)) for h in habits]
    candidates += [
        (COUNTDOWN, c.id, next_fire(COUNTDOWN, c, profile, now)) for c in countdowns
    ]
    candidates.append((JOURNAL, profile.id, next_fire(JOURNAL, profile, profile, now)))

    rows = [
        {
            "profile_id": profile.id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "fire_at": fire_at,
        }
        for entity_type, entity_id, fire_at in candidates
        if fire_at is not None
    ]
    # Also the rows of this profile's tasks that still name another profile:
    # a task moved here with its project keeps its old row until rewritten.
    await db.execute(
        delete(ScheduledNotification).where(
            or_(
                ScheduledNotification.profile_id == profile.id,
                and_(
                    ScheduledNotification.entity_type == TASK,
                    ScheduledNotification.entity_id.in_(
                        select(Task.id).where(Task.profile_id == profile.id)
                    ),
                ),
            )
        )
    )
    # One INSERT per chunk: asyncpg allows 32767 bind parameters per statement.
    chunk = CONFIG["scheduler"]["upsert_chunk"]
    for start in range(0, len(rows), chunk):
        await db.execute(_upsert(rows[start : start + chunk]))
    if rows:
        _poke_on_commit(db, min(row["fire_at"] for row in rows))


# --- Delivery ----------------------------------------------------------------

Sender = Callable[[PushSubscription, dict[str, str]], Awaitable[int]]
"""Sends one payload to one subscription and returns the push service's HTTP
status (`web_push.send`; tests pass a fake)."""

_ENTITY_MODELS: dict[str, type] = {
    TASK: Task,
    HABIT: Habit,
    COUNTDOWN: Countdown,
    JOURNAL: Profile,
}
_GONE_STATUSES = (404, 410)


async def _load(
    db: AsyncSession, row: ScheduledNotification
) -> tuple[Task | Habit | Countdown | Profile, Profile] | None:
    """The row's entity and the profile that owns it *now*, or None if either is gone.

    The profile comes from the entity, not `row.profile_id`: a row can outlive
    a move of its task to another profile, and the notification must go to the
    devices of the profile the entity lives in.
    """
    model = _ENTITY_MODELS.get(row.entity_type)
    entity = await db.get(model, row.entity_id) if model else None
    if entity is None:
        return None
    if isinstance(entity, Profile):
        return entity, entity
    profile = await db.get(Profile, entity.profile_id)
    return (entity, profile) if profile else None


async def _already_done(
    db: AsyncSession,
    entity_type: str,
    entity: Task | Habit | Countdown | Profile,
    profile: Profile,
    fire_at: datetime,
) -> bool:
    """Whether the thing the reminder asks for was already done that local day:
    a habit tracked as completed or skipped, or a journal entry written."""
    zone = _zone(profile)
    if zone is None:
        return False
    day = _local_today(fire_at, zone)
    if entity_type == HABIT:
        query = select(Tracker.id).where(
            Tracker.habit_id == entity.id,
            Tracker.dated == day,
            Tracker.status.in_([TrackerStatus.COMPLETED, TrackerStatus.SKIPPED]),
        )
    elif entity_type == JOURNAL:
        query = select(JournalEntry.id).where(
            JournalEntry.profile_id == entity.id, JournalEntry.entry_date == day
        )
    else:
        return False
    return await db.scalar(query.limit(1)) is not None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _payload(
    entity: Task | Habit | Countdown | Profile, profile: Profile, fire_at: datetime
) -> dict[str, str]:
    """`{title, body, url}`, title and body clipped so the encrypted record
    stays under the push services' 4096 byte cap. The urls are the front-end
    routes (its `src/app/routes.ts`): tasks and habits by slug, the countdown
    and journal pages being single pages."""
    if isinstance(entity, Task):
        title = entity.title
        body = task_body(entity, profile, fire_at)
        url = f"/tasks/{entity.slug}"
    elif isinstance(entity, Habit):
        title = entity.name
        body = entity.question.strip() or "Time to check in"
        url = f"/habits/{entity.slug}"
    elif isinstance(entity, Countdown):
        title, body, url = entity.title, "Today", "/countdown"
    else:
        title, body, url = "Journal", "Time to journal", "/journal"
    push = CONFIG["push"]
    return {
        "title": _clip(title, push["max_title_chars"]),
        "body": _clip(body, push["max_body_chars"]),
        "url": url,
    }


async def _send_all(
    send: Sender, pairs: list[tuple[PushSubscription, dict[str, str]]]
) -> list[int | BaseException]:
    """Send every (subscription, payload) pair, a bounded number at a time.

    Returns each pair's status, or the exception its send raised, in order.
    """
    gate = asyncio.Semaphore(CONFIG["push"]["max_concurrent_sends"])

    async def one(subscription: PushSubscription, payload: dict[str, str]) -> int:
        async with gate:
            return await send(subscription, payload)

    return await asyncio.gather(
        *(one(sub, payload) for sub, payload in pairs), return_exceptions=True
    )


async def _settle(
    db: AsyncSession, subscription: PushSubscription, result: int | BaseException
) -> bool:
    """Apply one send's outcome: delete a subscription the push service reports
    gone (404/410), log any other failure. Returns whether it was delivered."""
    if isinstance(result, BaseException):
        logger.error("Push to subscription %s failed", subscription.id, exc_info=result)
        return False
    if result in _GONE_STATUSES:
        await db.delete(subscription)
        return False
    if result >= 400:
        logger.warning(
            "Push to subscription %s answered status %s", subscription.id, result
        )
        return False
    return True


async def _subscriptions(db: AsyncSession, profile: Profile) -> list[PushSubscription]:
    result = await db.scalars(
        select(PushSubscription).where(PushSubscription.profile_id == profile.id)
    )
    return list(result)


async def deliver(
    db: AsyncSession, send: Sender, profile: Profile, payload: dict[str, str]
) -> bool:
    """Send `payload` to each of the profile's subscriptions and clean up gone
    ones; returns whether at least one was delivered. The caller commits."""
    subscriptions = await _subscriptions(db, profile)
    results = await _send_all(send, [(sub, payload) for sub in subscriptions])
    delivered = False
    for subscription, result in zip(subscriptions, results, strict=True):
        delivered = await _settle(db, subscription, result) or delivered
    return delivered


@dataclass
class _Send:
    """A row that passed its fire-time checks, with what its send needs."""

    row: ScheduledNotification
    entity: Task | Habit | Countdown | Profile
    profile: Profile
    payload: dict[str, str]
    subscriptions: list[PushSubscription]


async def _advance(
    db: AsyncSession,
    row: ScheduledNotification,
    entity: Task | Habit | Countdown | Profile,
    profile: Profile,
    now: datetime,
) -> None:
    """Move the row to the entity's next fire time after `now`, or delete it."""
    upcoming = next_fire(row.entity_type, entity, profile, now)
    if upcoming is None:
        await db.delete(row)
    else:
        row.profile_id = profile.id
        row.fire_at = upcoming


async def _recover(
    db: AsyncSession,
    row: ScheduledNotification,
    now: datetime,
    loaded: tuple[Task | Habit | Countdown | Profile, Profile] | None = None,
) -> None:
    """After a row raised, advance it so a recurring reminder survives one bad
    send; delete it when the entity is gone or advancing fails too."""
    try:
        loaded = loaded or await _load(db, row)
        if loaded:
            await _advance(db, row, *loaded, now)
            return
    except Exception:
        logger.exception("Advancing notification row %s failed", row.id)
    await db.delete(row)


async def _plan(
    db: AsyncSession, row: ScheduledNotification, now: datetime
) -> _Send | None:
    """Decide what a claimed row does. Returns the send to make, or None after
    settling the row itself (deleted, or advanced without sending).

    A row is stale, and sends nothing, when its entity no longer produces
    `row.fire_at` (a toggle turned off, a task closed or re-dated): asking the
    rule for the first instant after one microsecond earlier must give back
    exactly this instant. A row more than `late_grace_seconds` overdue is
    advanced without sending.
    """
    loaded = await _load(db, row)
    if loaded is None:
        await db.delete(row)
        return None
    entity, profile = loaded

    just_before = row.fire_at - timedelta(microseconds=1)
    current = next_fire(row.entity_type, entity, profile, just_before) == row.fire_at
    grace = timedelta(seconds=CONFIG["scheduler"]["late_grace_seconds"])
    if (
        current
        and now - row.fire_at <= grace
        and not await _already_done(db, row.entity_type, entity, profile, row.fire_at)
    ):
        return _Send(
            row,
            entity,
            profile,
            _payload(entity, profile, row.fire_at),
            await _subscriptions(db, profile),
        )
    await _advance(db, row, entity, profile, now)
    return None


async def fire_due(db: AsyncSession, send: Sender, now: datetime) -> int:
    """Send every reminder due at `now` and advance its row; returns how many
    reached at least one subscription.

    Rows are claimed `FOR UPDATE SKIP LOCKED`, so a second worker running the
    same pass skips rows the first holds instead of sending them again. A batch
    is planned row by row, sent concurrently (the row locks are held meanwhile,
    so the sends are bounded in number and time), then settled and committed
    once: a crash in between resends that batch on the next pass
    (at-least-once). That guarantee covers crashes only: a send that fails
    with a 5xx or a network error still advances the row, so that reminder is
    lost. A row that raises while being planned or settled is logged and
    advanced to its next fire time (deleted if that fails too); one bad row
    must not stop the batch. Every claimed row ends up deleted or moved past `now`, so
    claiming repeats until a batch comes back short.
    """
    batch = CONFIG["scheduler"]["claim_batch"]
    sent = 0
    while True:
        claimed = (
            await db.scalars(
                select(ScheduledNotification)
                .where(ScheduledNotification.fire_at <= now)
                .order_by(ScheduledNotification.fire_at, ScheduledNotification.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        sends: list[_Send] = []
        for row in claimed:
            try:
                plan = await _plan(db, row, now)
            except Exception:
                logger.exception("Notification row %s failed", row.id)
                await _recover(db, row, now)
                continue
            if plan:
                sends.append(plan)

        pairs = [(sub, plan.payload) for plan in sends for sub in plan.subscriptions]
        results = await _send_all(send, pairs)
        offset = 0
        for plan in sends:
            count = len(plan.subscriptions)
            plan_results = results[offset : offset + count]
            offset += count
            try:
                delivered = False
                for subscription, result in zip(
                    plan.subscriptions, plan_results, strict=True
                ):
                    ok = await _settle(db, subscription, result)
                    delivered = delivered or ok
                sent += delivered
                await _advance(db, plan.row, plan.entity, plan.profile, now)
            except Exception:
                logger.exception("Notification row %s failed", plan.row.id)
                await _recover(db, plan.row, now, (plan.entity, plan.profile))
        await db.commit()
        if len(claimed) < batch:
            return sent


async def run(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    send: Sender,
) -> None:
    """The scheduler loop: fire what is due, then sleep until the earliest row.

    Sleeps until `_next_at`, but never longer than `max_sleep_seconds` (that
    bound picks up rows changed outside the API), and wakes early when `poke`
    reports a sooner row. A failed pass is logged and the loop carries on.
    Runs until cancelled.
    """
    global _next_at, _wake
    config = CONFIG["scheduler"]
    _wake = asyncio.Event()
    while True:
        # Reset before reading the schedule: a poke from here on is either seen
        # by the read or leaves the event set for the sleep below.
        _wake.clear()
        _next_at = None
        failed = False
        try:
            async with session_factory() as db:
                await fire_due(db, send, utc_now())
                earliest = await db.scalar(
                    select(func.min(ScheduledNotification.fire_at))
                )
            if earliest is not None and (_next_at is None or earliest < _next_at):
                _next_at = earliest
        except Exception:
            logger.exception("Notification pass failed")
            failed = True

        deadline = utc_now() + timedelta(seconds=config["max_sleep_seconds"])
        if failed:
            deadline = utc_now() + timedelta(seconds=config["error_backoff_seconds"])
        elif _next_at is not None:
            deadline = min(deadline, _next_at)
        # The floor stops a row another worker holds locked (so still due, and
        # skipped) from turning the loop into a spin.
        delay = max((deadline - utc_now()).total_seconds(), config["min_sleep_seconds"])
        with suppress(TimeoutError):
            await asyncio.wait_for(_wake.wait(), delay)
