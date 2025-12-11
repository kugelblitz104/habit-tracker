from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_resource_access,
    get_current_user,
    get_db,
)
from habit_tracker.core.security import get_password_hash
from habit_tracker.models import (
    Habit,
    HabitList,
    HabitRead,
    Tracker,
    User,
    UserList,
    UserRead,
    UserUpdate,
)

router = APIRouter(
    prefix="/users", tags=["users"], responses={404: {"description": "Not found"}}
)


@router.get("/{user_id}", summary="Get a user by ID")
async def read_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    """
    Retrieve a specific user by their ID.

    - **user_id**: The unique identifier of the user to retrieve
    """
    authorize_resource_access(current_user, user_id, "user")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserRead.model_validate(user)


@router.get("/{user_id}/habits", summary="List all habits for a user")
async def list_user_habits(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of habits to return (1-100)",
    ),
) -> HabitList:
    """
    Get a paginated list of all habits belonging to a specific user.

    - **user_id**: The unique identifier of the user
    - **limit**: Maximum number of habits to return (default: 5, max: 100)
    """
    authorize_resource_access(current_user, user_id, "user")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    result = await db.execute(
        select(Habit).filter(Habit.user_id == user_id).limit(limit)
    )
    db_habits = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(Habit.user_id == user_id)
    )
    total = count_result.scalar() or 0

    today = datetime.now().date()
    habit_ids = [h.id for h in db_habits]

    today_trackers = {}
    if habit_ids:
        tracker_result = await db.execute(
            select(Tracker).filter(
                Tracker.habit_id.in_(habit_ids), Tracker.dated == today
            )
        )
        for tracker in tracker_result.scalars().all():
            today_trackers[tracker.habit_id] = tracker

    # Build HabitRead objects with today's status
    habits_read = []
    for habit in db_habits:
        habit_read = HabitRead.model_validate(habit)
        tracker = today_trackers.get(habit.id)
        habit_read.completed_today = tracker.completed if tracker else False
        habit_read.skipped_today = tracker.skipped if tracker else False
        habits_read.append(habit_read)

    return HabitList(
        habits=habits_read,
        total=total,
        limit=limit,
        offset=0,
    )


@router.put("/{user_id}", summary="Replace a user (full update)")
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    """
    Replace all fields of an existing user. All fields must be provided.

    This performs a full replacement of the user resource.
    Use PATCH if you want to update only specific fields.

    - **user_id**: The unique identifier of the user to update
    """
    authorize_resource_access(current_user, user_id, "user")
    db_user = await db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user_data = user_update.model_dump()
    user_data["password_hash"] = get_password_hash(user_data.pop("plaintext_password"))
    for key, value in user_data.items():
        setattr(db_user, key, value)
    await db.commit()
    await db.refresh(db_user)
    return UserRead.model_validate(db_user)


@router.patch("/{user_id}", summary="Update a user (partial update)")
async def patch_user(
    user_id: int,
    user_update: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
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
    - **plaintext_password**: New password for the user
    """
    authorize_resource_access(current_user, user_id, "user")
    db_user = await db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user_data = user_update.model_dump(exclude_unset=True)
    if "plaintext_password" in user_data:
        user_data["password_hash"] = get_password_hash(
            user_data.pop("plaintext_password")
        )
    for key, value in user_data.items():
        setattr(db_user, key, value)
    await db.commit()
    await db.refresh(db_user)
    return UserRead.model_validate(db_user)


@router.delete("/{user_id}", summary="Delete a user")
async def delete_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a user by their ID.

    - **user_id**: The unique identifier of the user to delete

    This action cannot be undone.
    """
    authorize_resource_access(current_user, user_id, "user")
    db_user = await db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    await db.delete(db_user)
    await db.commit()
    return JSONResponse(
        content={"detail": "User deleted successfully"}, status_code=status.HTTP_200_OK
    )


@router.get("/", summary="List all users")
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(
        default=5, ge=1, le=100, description="Maximum number of users to return (1-100)"
    ),
) -> UserList:
    """
    Get a paginated list of all users in the system.
    Regular users can only see their own account.
    Admins can see all users.

    - **limit**: Maximum number of users to return (default: 5, max: 100)

    Returns a list of users with pagination metadata including total count.
    """
    if current_user.is_admin:
        # Admins can see all users
        result = await db.execute(select(User).limit(limit))
        db_users = result.scalars().all()

        count_result = await db.execute(select(func.count()).select_from(User))
        total = count_result.scalar() or 0

        return UserList(
            users=[UserRead.model_validate(u) for u in db_users],
            total=total,
            limit=limit,
            offset=0,
        )
    else:
        # Regular users can only see themselves
        return UserList(
            users=[UserRead.model_validate(current_user)],
            total=1,
            limit=limit,
            offset=0,
        )
