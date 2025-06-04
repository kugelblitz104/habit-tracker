from ..models import habits, users
from sqlalchemy.orm import Session

def create_habit(db: Session, habit: habits.HabitCreate):
    db_habit = habits.Habit.model_validate(habit)
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return db_habit

def get_habit(db: Session, habit_id: int):
    habit = db.get(habits.Habit, habit_id)
    if not habit:
        return None
    return habits.HabitRead.model_validate(habit)

def update_habit(db: Session, habit_id: int, habit_update: habits.HabitUpdate):
    db_habit = db.get(habits.Habit, habit_id)
    if not db_habit:
        return None
    habit_data = habits.HabitUpdate.model_validate(habit_update)
    for key, value in habit_data.model_dump().items():
        if value is not None:
            setattr(db_habit, key, value)
    db.commit()
    db.refresh(db_habit)
    return habits.HabitRead.model_validate(db_habit)

def delete_habit(db: Session, habit_id: int):
    db_habit = db.get(habits.Habit, habit_id)
    if not db_habit:
        return None
    db.delete(db_habit)
    db.commit()
    return habits.HabitDelete(id=habit_id)

def list_habits(db: Session, user_id: int):
    user = db.get(users.User, user_id)
    if not user:
        return habits.HabitList(habits=[])
    db_habits = db.query(habits.Habit).filter(getattr(habits.Habit, "user_id") == user_id).all()
    return habits.HabitList(habits=[habits.HabitRead.model_validate(h) for h in db_habits])