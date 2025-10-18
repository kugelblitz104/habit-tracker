from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from habit_tracker.core.dependencies import get_db
from habit_tracker.models import (
    Habit,
    HabitCreate,
    HabitRead,
    HabitUpdate,
    Tracker,
    TrackerRead,
)

router = APIRouter(
    prefix="/habits", tags=["habits"], responses={404: {"description": "Not found"}}
)


@router.post("/")
def create_habit(habit: HabitCreate, db: Annotated[Session, Depends(get_db)]):
    db_habit = Habit(**habit.model_dump())
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)


@router.get("/{habit_id}")
def read_habit(habit_id: int, db: Annotated[Session, Depends(get_db)]):
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return HabitRead.model_validate(habit)


@router.get("/{habit_id}/trackers")
def list_habit_trackers(
    habit_id: int, db: Annotated[Session, Depends(get_db)], limit: int = 5
):
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db_trackers = (
        db.query(Tracker)
        .filter(getattr(Tracker, "habit_id") == habit_id)
        .limit(limit)
        .order_by(Tracker.dated.desc())
        .all()
    )
    return [TrackerRead.model_validate(t) for t in db_trackers]


@router.put("/{habit_id}")
def update_habit(
    habit_id: int, habit_update: HabitUpdate, db: Annotated[Session, Depends(get_db)]
):
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
def delete_habit(habit_id: int, db: Annotated[Session, Depends(get_db)]):
    db_habit = db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db.delete(db_habit)
    db.commit()
    return {"detail": "Habit deleted successfully"}
