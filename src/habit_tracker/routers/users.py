from fastapi import APIRouter, Depends, HTTPException
from ..core.dependencies import get_db
from ..models import *
from typing import Annotated
from sqlalchemy.orm import Session

router = APIRouter(
    prefix='/users',
    tags=['users'],
    responses={404: {"description": "Not found"}}
)

@router.post('/')
def create_user(user: UserCreate, db: Annotated[Session, Depends(get_db)]):
    db_user = User.model_validate(user)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return UserRead.model_validate(db_user)

@router.get('/{user_id}')
def read_user(user_id: int, db: Annotated[Session, Depends(get_db)]):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserRead.model_validate(user)

@router.get('/{user_id}/habits')
def list_user_habits(user_id: int, db: Annotated[Session, Depends(get_db)], limit: int = 5):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db_habits = db.query(Habit).filter(getattr(Habit, "user_id") == user_id).limit(limit).all()
    return HabitList(habits=[HabitRead.model_validate(h) for h in db_habits])

@router.put('/{user_id}')
def update_user(user_id: int, user_update: UserUpdate, db: Annotated[Session, Depends(get_db)]):
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = UserUpdate.model_validate(user_update)
    for key, value in user_data.model_dump().items():
        if value is not None:
            setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return UserRead.model_validate(db_user)

@router.delete('/{user_id}')
def delete_user(user_id: int, db: Annotated[Session, Depends(get_db)]):
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return {"detail": "User deleted successfully"}

@router.get('/')
def list_users(db: Annotated[Session, Depends(get_db)], limit: int = 5):
    db_users = db.query(User).limit(limit).all()
    return UserList(users=[UserRead.model_validate(u) for u in db_users])
