from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.constants import TrackerStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.core.dependencies import resolve_habit_profile_id, resolve_today
from habit_tracker.core.slugs import allocate_slug
from habit_tracker.models import HabitRead
from habit_tracker.schemas.db_models import Habit, Profile, Tracker
from habit_tracker.services.notifications import HABIT, reschedule

# The columns a TrackerLite reads, so the lite reads skip whole ORM rows and
# never fetch note bodies. has_note: the note holds any non-whitespace character.
TRACKER_LITE_COLUMNS = (
    Tracker.id,
    Tracker.dated,
    Tracker.status,
    func.coalesce(Tracker.note.regexp_match(r"\S"), False).label("has_note"),
)


async def habit_to_read(db: AsyncSession, habit: Habit, tz: str | None) -> HabitRead:
    """A HabitRead with today's completed/skipped flags resolved in `tz`.

    Shared by the by-id and by-slug reads so the two cannot drift; the list
    endpoint computes the same flags in bulk for a whole page instead.
    """
    habit_read: HabitRead = HabitRead.model_validate(habit)
    today = resolve_today(tz)
    today_tracker = (
        await db.execute(
            select(Tracker)
            .filter(Tracker.habit_id == habit.id, Tracker.dated == today)
            .limit(1)
        )
    ).scalar()

    habit_read.completed_today = (
        today_tracker.status == TrackerStatus.COMPLETED if today_tracker else False
    )
    habit_read.skipped_today = (
        today_tracker.status == TrackerStatus.SKIPPED if today_tracker else False
    )
    return habit_read


async def apply_habit_update(
    db: AsyncSession, db_habit: Habit, profile: Profile, habit_data: dict
) -> None:
    """Apply an update dict to a habit - shared by PUT (full model_dump) and
    PATCH (model_dump(exclude_unset=True)).

    profile_id is resolved against the habit's current owner (taken from the
    habit's owning profile), not the caller: an admin editing another user's
    habit may only use that user's profiles. A None/omitted profile_id keeps
    the habit's current profile - profile_id is never nulled.
    """
    if habit_data.get("profile_id") is None:
        habit_data.pop("profile_id", None)
    else:
        habit_data["profile_id"] = await resolve_habit_profile_id(
            db, profile.user_id, habit_data["profile_id"]
        )
    # PUT dumps every field, so an omitted mask arrives as None; keep the stored
    # one (PATCH already rejects an explicit null).
    if habit_data.get("reminder_days") is None:
        habit_data.pop("reminder_days", None)
    previous_name = db_habit.name
    previous_profile_id = db_habit.profile_id

    for key, value in habit_data.items():
        setattr(db_habit, key, value)

    # Re-slug when the name changes (the slug tracks the name, so renaming a
    # habit changes its URL and the old one stops resolving - the numeric URL
    # always keeps working). Also re-slug on a profile move, since slugs are
    # unique per profile and the clean slug may already be taken in the new one.
    # Here rather than in the two routes so PUT and PATCH cannot drift.
    if db_habit.name != previous_name or db_habit.profile_id != previous_profile_id:
        db_habit.slug = await allocate_slug(
            db,
            Habit,
            profile_id=db_habit.profile_id,
            source=db_habit.name,
            exclude_id=db_habit.id,
        )

    db_habit.updated_date = utc_now()  # server-stamped, never client-set
    await reschedule(db, HABIT, db_habit)
