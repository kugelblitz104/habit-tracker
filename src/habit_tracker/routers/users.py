from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from habit_tracker.core.dependencies import get_db
from habit_tracker.models import (
    Habit,
    HabitList,
    HabitRead,
    User,
    UserCreate,
    UserList,
    UserRead,
    UserUpdate,
)

router = APIRouter(
    prefix="/users", tags=["users"], responses={404: {"description": "Not found"}}
)


@router.post("/", status_code=201, summary="Create a new user")
def create_user(user: UserCreate, db: Annotated[Session, Depends(get_db)]) -> UserRead:
    """
    Create a new user with the following information:

    - **username**: Unique username for the user
    - **first_name**: User's first name
    - **last_name**: User's last name
    - **email**: User's email address
    - **password_hash**: Hashed password for authentication
    """
    db_user = User(**user.model_dump())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return UserRead.model_validate(db_user)


@router.get("/{user_id}", summary="Get a user by ID")
def read_user(user_id: int, db: Annotated[Session, Depends(get_db)]) -> UserRead:
    """
    Retrieve a specific user by their ID.

    - **user_id**: The unique identifier of the user to retrieve
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserRead.model_validate(user)


@router.get("/{user_id}/habits", summary="List all habits for a user")
def list_user_habits(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=5, ge=1, le=100, description="Maximum number of habits to return (1-100)"),
) -> HabitList:
    """
    Get a paginated list of all habits belonging to a specific user.

    - **user_id**: The unique identifier of the user
    - **limit**: Maximum number of habits to return (default: 5, max: 100)
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db_habits = db.query(Habit).filter(Habit.user_id == user_id).limit(limit).all()
    return HabitList(
        habits=[HabitRead.model_validate(h) for h in db_habits],
        total=db.query(Habit).filter(Habit.user_id == user_id).count(),
        limit=limit,
        offset=0,
    )


@router.put("/{user_id}", summary="Replace a user (full update)")
def update_user(
    user_id: int, user_update: UserUpdate, db: Annotated[Session, Depends(get_db)]
) -> UserRead:
    """
    Replace all fields of an existing user. All fields must be provided.

    This performs a full replacement of the user resource.
    Use PATCH if you want to update only specific fields.

    - **user_id**: The unique identifier of the user to update
    """
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_update.model_dump()
    for key, value in user_data.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return UserRead.model_validate(db_user)


@router.patch("/{user_id}", summary="Update a user (partial update)")
def patch_user(
    user_id: int, user_update: UserUpdate, db: Annotated[Session, Depends(get_db)]
) -> UserRead:
    """
    Update specific fields of an existing user. Only provided fields will be updated.

    This performs a partial update of the user resource.
    Use PUT if you want to replace the entire resource.

    - **user_id**: The unique identifier of the user to update

    You can update any combination of these fields:
    - **username**: Unique username for the user
    - **first_name**: User's first name
    - **last_name**: User's last name
    - **email**: User's email address
    - **password_hash**: Hashed password for authentication
    """
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_update.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return UserRead.model_validate(db_user)


@router.delete("/{user_id}", summary="Delete a user")
def delete_user(user_id: int, db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    """
    Delete a user by their ID.

    - **user_id**: The unique identifier of the user to delete

    This action cannot be undone.
    """
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return JSONResponse(
        content={"detail": "User deleted successfully"}, status_code=200
    )


@router.get("/", summary="List all users")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=5, ge=1, le=100, description="Maximum number of users to return (1-100)")
) -> UserList:
    """
    Get a paginated list of all users in the system.

    - **limit**: Maximum number of users to return (default: 5, max: 100)

    Returns a list of users with pagination metadata including total count.
    """
    db_users = db.query(User).limit(limit).all()
    return UserList(
        users=[UserRead.model_validate(u) for u in db_users],
        total=db.query(User).count(),
        limit=limit,
        offset=0,
    )
