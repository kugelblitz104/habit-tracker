from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.dependencies import (
    authorize_resource_access,
    get_current_user,
    get_db,
)
from habit_tracker.models import (
    Profile,
    ProfileCreate,
    ProfileList,
    ProfileRead,
    ProfileUpdate,
)
from habit_tracker.schemas.db_models import User

router = APIRouter(
    prefix="/profiles", tags=["profiles"], responses={404: {"description": "Not found"}}
)


def _profile_integrity_error(exc: IntegrityError) -> HTTPException:
    """Map an IntegrityError on a profile write to an HTTP 409.

    Only claims a duplicate name when the unique constraint on
    (user_id, name) is actually the one that fired.
    """
    if "uix_profile_user_name" in str(exc.orig or exc):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A profile with this name already exists for this user",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Profile change violates a database constraint",
    )


@router.get("/", summary="List profiles for the current user")
async def list_profiles(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    user_id: Optional[int] = Query(
        default=None,
        description="List another user's profiles (admins only)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
        description="Maximum number of profiles to return (1-100)",
    ),
    offset: int = Query(default=0, ge=0, description="Number of profiles to skip"),
) -> ProfileList:
    """
    Get the current user's profiles, ordered by creation date.

    - **user_id**: Optional. Admins may pass another user's ID to list that
      user's profiles. Non-admins may only list their own.
    - **limit**: Maximum number of profiles to return (default: 100, max: 100)
    - **offset**: Number of profiles to skip (default: 0)
    """
    target_user_id = user_id if user_id is not None else current_user.id
    authorize_resource_access(current_user, target_user_id, "profile")

    result = await db.execute(
        select(Profile)
        .filter(Profile.user_id == target_user_id)
        .order_by(Profile.created_date)
        .limit(limit)
        .offset(offset)
    )
    db_profiles = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).filter(Profile.user_id == target_user_id)
    )
    total = count_result.scalar() or 0

    return ProfileList(
        profiles=[ProfileRead.model_validate(p) for p in db_profiles],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new profile")
async def create_profile(
    profile: ProfileCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProfileRead:
    """
    Create a new profile for the current user with the following information:

    - **name**: Name of the profile (unique per user, e.g. "Personal", "Work")
    - **color_start**: Starting hex color of the avatar gradient
    - **color_end**: Ending hex color of the avatar gradient
    - **habits_enabled**: Whether the habits surface is enabled for this profile
    - **calendar_enabled**: Whether the calendar surface is enabled for this profile
    - **publish_to_azure**: Whether to publish tasks to Azure DevOps (placeholder)
    - **default_landing**: Landing page for this profile ('today' or 'habits')

    Profiles are personal - they always belong to the authenticated user.
    """
    db_profile = Profile(**profile.model_dump(), user_id=current_user.id)
    db.add(db_profile)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _profile_integrity_error(exc)
    await db.refresh(db_profile)
    return ProfileRead.model_validate(db_profile)


@router.get("/{profile_id}", summary="Get a profile by ID")
async def read_profile(
    profile_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProfileRead:
    """
    Retrieve a specific profile by its ID.

    - **profile_id**: The unique identifier of the profile to retrieve
    """
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )

    authorize_resource_access(current_user, profile.user_id, "profile")
    return ProfileRead.model_validate(profile)


@router.patch("/{profile_id}", summary="Update a profile (partial update)")
async def patch_profile(
    profile_id: int,
    profile_update: ProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProfileRead:
    """
    Update specific fields of an existing profile. Only provided fields will be updated.

    - **profile_id**: The unique identifier of the profile to update

    You can update any combination of these fields:
    - **name**: Name of the profile (unique per user)
    - **color_start**: Starting hex color of the avatar gradient
    - **color_end**: Ending hex color of the avatar gradient
    - **habits_enabled**: Whether the habits surface is enabled for this profile
    - **calendar_enabled**: Whether the calendar surface is enabled for this profile
    - **publish_to_azure**: Whether to publish tasks to Azure DevOps (placeholder)
    - **default_landing**: Landing page for this profile ('today' or 'habits')
    """
    db_profile = await db.get(Profile, profile_id)
    if not db_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    authorize_resource_access(current_user, db_profile.user_id, "profile")

    profile_data = profile_update.model_dump(exclude_unset=True)
    for key, value in profile_data.items():
        setattr(db_profile, key, value)
    db_profile.updated_date = datetime.now()  # server-stamped, never client-set
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _profile_integrity_error(exc)
    await db.refresh(db_profile)
    return ProfileRead.model_validate(db_profile)


@router.delete("/{profile_id}", summary="Delete a profile")
async def delete_profile(
    profile_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """
    Delete a profile by its ID.

    - **profile_id**: The unique identifier of the profile to delete

    This action cannot be undone. All habits, projects, and tasks belonging
    to the profile are cascade deleted. A user's last remaining profile
    cannot be deleted.
    """
    db_profile = await db.get(Profile, profile_id)
    if not db_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    authorize_resource_access(current_user, db_profile.user_id, "profile")

    count_result = await db.execute(
        select(func.count()).filter(Profile.user_id == db_profile.user_id)
    )
    profile_count = count_result.scalar() or 0
    if profile_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the user's last profile",
        )

    await db.delete(db_profile)  # habits, projects, and tasks are cascade deleted
    await db.commit()
    return JSONResponse(
        content={
            "detail": "Profile deleted successfully, along with its habits, projects, and tasks"
        }
    )
