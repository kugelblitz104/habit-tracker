from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from habit_tracker.core.dependencies import get_db
from habit_tracker.models import (
    Habit,
    HabitCreate,
    HabitKPIs,
    HabitRead,
    HabitUpdate,
    Tracker,
    TrackerRead,
    Streak,
)

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.post("/")
def create_habit(
    habit: HabitCreate, db: Annotated[Session, Depends(get_db)]
) -> HabitRead:
    db_habit = Habit(**habit.model_dump())
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.get("/{habit_id}")
def read_habit(habit_id: int, db: Annotated[Session, Depends(get_db)]) -> HabitRead:
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return HabitRead.model_validate(habit)


@router.get("/{habit_id}/trackers")
def list_habit_trackers(
    habit_id: int,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=5, ge=1, le=100),
) -> list[TrackerRead]:
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db_trackers = (
        db.query(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .order_by(Tracker.dated.desc())
        .limit(limit if limit > 0 else None)
        .all()
    )
    return [TrackerRead.model_validate(t) for t in db_trackers]


@router.get("/{habit_id}/kpis")
def get_habit_kpis(habit_id: int, db: Annotated[Session, Depends(get_db)]) -> HabitKPIs:
    habit = read_habit(habit_id, db=db)

    thirty_day_completions = (
        db.query(Tracker)
        .filter(
            Tracker.habit_id == habit_id,
            Tracker.dated >= datetime.now() - timedelta(days=30),
        )
        .count()
    )

    count_completions = db.query(Tracker).filter(Tracker.habit_id == habit_id).count()
    days_active = (datetime.now() - habit.created_date).days

    last_tracker = (
        db.query(Tracker)
        .filter(Tracker.habit_id == habit_id)
        .order_by(Tracker.dated.desc())
        .first()
    )

    streaks = get_habit_streaks(habit_id, db=db)
    if len(streaks) > 0:
        current_streak = streaks[-1].length()
        longest_streak = max((s.length() for s in streaks), default=0)

    kpis = HabitKPIs(
        id=habit.id,
        current_streak=current_streak if len(streaks) > 0 else 0,
        longest_streak=longest_streak if len(streaks) > 0 else 0,
        total_completions=count_completions,
        thirty_day_completion_rate=(
            thirty_day_completions / 30 if thirty_day_completions > 0 else 0
        ),
        overall_completion_rate=(
            count_completions / days_active if days_active > 0 else 0
        ),
        last_completed_date=last_tracker.dated if last_tracker else None,
    )

    return HabitKPIs.model_validate(kpis)


@router.get("/{habit_id}/streaks")
def get_habit_streaks(
    habit_id, db: Annotated[Session, Depends(get_db)]
) -> list[Streak]:
    habit = read_habit(habit_id, db)
    days_since_created = (datetime.now().date() - habit.created_date.date()).days

    all_trackers = list_habit_trackers(habit_id, db=db, limit=days_since_created + 1)
    completed_dates = [x.dated for x in all_trackers if x.completed]
    skipped_dates = [x.dated for x in all_trackers if x.skipped]

    streak_continued = []

    for days_since in range(days_since_created + 1):
        moving_date = habit.created_date.date() + timedelta(days=days_since)
        window_start = moving_date - timedelta(days=habit.range - 1)

        # Count completions in window
        completions = sum(
            1 for d in completed_dates if window_start <= d <= moving_date
        )

        if completions >= habit.frequency:
            streak_continued.append(moving_date)

    streak_continued.extend([x for x in skipped_dates if x not in streak_continued])
    streak_continued.sort()

    streaks = []
    moving_streak = None

    for streak_day in streak_continued:
        if moving_streak:
            # Check if this day is within tolerance of the last streak day
            gap = (streak_day - moving_streak.end_date).days
            if gap <= habit.range:
                moving_streak.end_date = streak_day
            else:
                # Gap too large, start new streak
                streaks.append(moving_streak)
                moving_streak = Streak.from_date(
                    streak_day - timedelta(days=habit.range - 1)
                )
                moving_streak.end_date = streak_day
        else:
            # Start new streak, backdated by the range
            moving_streak = Streak.from_date(
                streak_day - timedelta(days=habit.range - 1)
            )
            moving_streak.end_date = streak_day

    if moving_streak:
        streaks.append(moving_streak)
    return streaks


@router.put("/{habit_id}")
def update_habit(
    habit_id: int, habit_update: HabitUpdate, db: Annotated[Session, Depends(get_db)]
) -> HabitRead:
    db_habit = db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit_data = habit_update.model_dump(exclude_unset=True)
    for key, value in habit_data.items():
        setattr(db_habit, key, value)
    db.commit()
    db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.delete("/{habit_id}")
def delete_habit(
    habit_id: int, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    db_habit = db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db.delete(db_habit)
    db.commit()
    return JSONResponse(content={"detail": "Habit deleted successfully"})
