from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import desc
from ..core.dependencies import get_db
from ..models import *
from typing import Annotated
from sqlalchemy.orm import Session

router = APIRouter(
    prefix='/habits',
    tags=['habits'],
    responses={404: {"description": "Not found"}}
)

@router.post('/')
def create_habit(habit: HabitCreate, db: Annotated[Session, Depends(get_db)]):
    db_habit = Habit.model_validate(habit)
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)

@router.get('/{habit_id}')
def read_habit(habit_id: int, db: Annotated[Session, Depends(get_db)]):
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return HabitRead.model_validate(habit)

@router.get('/{habit_id}/trackers')
def list_habit_trackers(habit_id: int, db: Annotated[Session, Depends(get_db)], limit: int = 5):
    habit = db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db_trackers = db.query(Tracker).filter(getattr(Tracker, "habit_id") == habit_id).limit(limit).order_by(desc(Tracker.dated)).all()
    return [TrackerRead.model_validate(t) for t in db_trackers]

@router.put('/{habit_id}')
def update_habit(habit_id: int, habit_update: HabitUpdate, db: Annotated[Session, Depends(get_db)]):
    db_habit = db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit_data = HabitUpdate.model_validate(habit_update)
    for key, value in habit_data.model_dump().items():
        if value is not None:
            setattr(db_habit, key, value)
    db.commit()
    db.refresh(db_habit)
    return HabitRead.model_validate(db_habit)

@router.delete('/{habit_id}')
def delete_habit(habit_id: int, db: Annotated[Session, Depends(get_db)]):
    db_habit = db.get(Habit, habit_id)
    if not db_habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    db.delete(db_habit)
    db.commit()
    return HabitDelete(id=habit_id)

# @router.get('/')
# def list_habits(user_id: int, db: Annotated[Session, Depends(get_db)], limit: int = 5):
#     user = db.get(User, user_id)
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")
#     db_habits = db.query(Habit).filter(getattr(Habit, "user_id") == user_id).limit(limit).all()
#     return HabitList(habits=[HabitRead.model_validate(h) for h in db_habits])