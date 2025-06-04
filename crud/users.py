from ..models import users
from sqlalchemy.orm import Session

def create_user(db: Session, user: users.UserCreate):
    db_user = users.User.model_validate(user)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user(db: Session, user_id: int):
    user = db.get(users.User, user_id)
    if not user:
        return None
    return users.UserRead.model_validate(user)

def update_user(db: Session, user_id: int, user_update: users.UserUpdate):
    db_user = db.get(users.User, user_id)
    if not db_user:
        return None
    user_data = users.UserUpdate.model_validate(user_update)
    for key, value in user_data.model_dump().items():
        if value is not None:
            setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return users.UserRead.model_validate(db_user)

def delete_user(db: Session, user_id: int):
    db_user = db.get(users.User, user_id)
    if not db_user:
        return None
    db.delete(db_user)
    db.commit()
    return users.UserDelete(id=user_id)

def list_users(db: Session):
    db_users = db.query(users.User).all()
    return users.UserList(users=[users.UserRead.model_validate(u) for u in db_users])