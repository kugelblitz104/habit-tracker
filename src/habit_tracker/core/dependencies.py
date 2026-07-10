import logging
from datetime import date, datetime
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from habit_tracker.database import SessionLocal
from habit_tracker.schemas.db_models import Habit, Profile, User
from habit_tracker.core.security import decode_token

logger = logging.getLogger(__name__)


async def get_db():
    async with SessionLocal() as db:
        try:
            yield db
        except Exception as e:
            await db.rollback()
            logger.error(f"Error occurred: {e}")
            raise
        finally:
            await db.close()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    payload = decode_token(token)

    if payload is None:
        logger.error("Token decode returned None")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        logger.error(f"Invalid token type: {token_type}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str = payload.get("sub")
    if user_id_str is None:
        logger.error("No user ID in token payload")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Convert string user_id to integer for database query
    try:
        user_id: int = int(user_id_str)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid user ID format: {user_id_str}, error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.execute(select(User).where(User.id == user_id))
    user = user.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user


def require_admin(current_user: User) -> User:
    """
    Dependency that requires the current user to be an admin.
    Raises 403 if the user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def is_admin_or_owner(current_user: User, resource_user_id: int) -> bool:
    """
    Check if the current user is an admin or the owner of the resource.

    Args:
        current_user: The authenticated user
        resource_user_id: The user_id of the resource being accessed

    Returns:
        True if the user is authorized (admin or owner), False otherwise
    """
    return current_user.is_admin or current_user.id == resource_user_id


def authorize_resource_access(
    current_user: User, resource_user_id: int, resource_name: str = "resource"
) -> None:
    """
    Authorize access to a resource. Raises 403 if unauthorized.

    Args:
        current_user: The authenticated user
        resource_user_id: The user_id of the resource being accessed
        resource_name: Name of the resource for error messages

    Raises:
        HTTPException: 403 if user is not authorized
    """
    if not is_admin_or_owner(current_user, resource_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Not authorized to access this {resource_name}",
        )


async def get_owned_profile(
    db: AsyncSession, profile_id: int, current_user: User, resource_name: str
) -> Profile:
    """
    Fetch a profile by ID and authorize the caller against its owner.

    Shared by every endpoint that receives an explicit profile_id (the
    profiles CRUD itself plus the profile-scoped task/project/calendar
    endpoints).

    Args:
        db: The database session
        profile_id: The ID of the profile to fetch
        current_user: The authenticated user
        resource_name: Name of the resource for the 403 error message

    Returns:
        The profile

    Raises:
        HTTPException: 404 if the profile does not exist, 403 if the caller
        is neither the profile's owner nor an admin
    """
    profile = await db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    authorize_resource_access(current_user, profile.user_id, resource_name)
    return profile


async def authorize_parent_profile(
    db: AsyncSession, profile_id: int, current_user: User, resource_name: str
) -> Profile:
    """
    Load the profile that owns a child resource (task/project/calendar
    connection) and authorize the caller against it.

    The child row's foreign key guarantees the profile exists, so unlike
    get_owned_profile there is no 404 check here.

    Args:
        db: The database session
        profile_id: The child resource's profile_id
        current_user: The authenticated user
        resource_name: Name of the resource for the 403 error message

    Returns:
        The parent profile

    Raises:
        HTTPException: 403 if the caller is neither the profile's owner nor
        an admin
    """
    profile = await db.get(Profile, profile_id)
    authorize_resource_access(current_user, profile.user_id, resource_name)
    return profile


async def get_owned_habit(
    db: AsyncSession, habit_id: int, current_user: User
) -> Habit:
    """
    Fetch a habit by ID and authorize the caller against its owner.

    Habits carry their owner's user_id directly (unlike the profile-scoped
    resources), so no profile lookup is needed.

    Args:
        db: The database session
        habit_id: The ID of the habit to fetch
        current_user: The authenticated user

    Returns:
        The habit

    Raises:
        HTTPException: 404 if the habit does not exist, 403 if the caller is
        neither the habit's owner nor an admin
    """
    habit = await db.get(Habit, habit_id)
    if not habit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
        )
    authorize_resource_access(current_user, habit.user_id, "habit")
    return habit


def resolve_timezone(tz: Optional[str]) -> Optional[ZoneInfo]:
    """
    Resolve an optional IANA timezone name (e.g. "America/New_York") from a
    query parameter into a ZoneInfo.

    Args:
        tz: The IANA timezone name, or None if the client did not send one

    Returns:
        The resolved ZoneInfo, or None when tz is None (callers keep their
        legacy server-local behavior)

    Raises:
        HTTPException: 422 if the name is not a valid IANA timezone, so a
        client typo surfaces as a validation error rather than a 500
    """
    if tz is None:
        return None
    try:
        return ZoneInfo(tz)
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid timezone '{tz}': must be a valid IANA timezone "
                "name, e.g. 'America/New_York'"
            ),
        )


def resolve_today(tz: Optional[str]) -> date:
    """
    Return "today" for an optional IANA timezone query parameter.

    datetime.now(None) is server-local time, so a missing tz keeps the
    legacy server-local behavior.

    Raises:
        HTTPException: 422 if the name is not a valid IANA timezone (see
        resolve_timezone)
    """
    return datetime.now(resolve_timezone(tz)).date()
