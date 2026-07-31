import logging
from datetime import date, datetime
from typing import Annotated, Protocol, TypeVar
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from habit_tracker.core.security import decode_token
from habit_tracker.database import SessionLocal
from habit_tracker.schemas.db_models import Habit, Profile, User

logger = logging.getLogger(__name__)


class _HasProfileId(Protocol):
    """Structural type for get_owned_child's model param - any ORM row with a
    profile_id column (Task, Project, Countdown, TimeEntry, ...).

    Annotated `Mapped[int]`, not `int`, so the SQLAlchemy models actually match:
    they declare `profile_id: Mapped[int]`, and a Protocol member typed `int`
    fails structurally against that, which made every call site a type error.
    """

    profile_id: Mapped[int]


T = TypeVar("T", bound=_HasProfileId)


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

    Deliberately unwired: no route uses this yet. Kept here as the canonical
    guard for the first genuinely admin-only endpoint, rather than having
    that endpoint reinvent the check.
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
        an admin, or (in practice unreachable - see above) 500 if the child
        row's profile_id doesn't actually reference an existing profile
    """
    profile = await db.get(Profile, profile_id)
    if profile is None:
        # The FK is supposed to make this impossible; if it ever fires, a
        # clear 500 beats an AttributeError on profile.user_id below.
        logger.error(
            "authorize_parent_profile: profile_id=%s has no matching Profile "
            "row despite an FK reference to it",
            profile_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Referenced profile is missing",
        )
    authorize_resource_access(current_user, profile.user_id, resource_name)
    return profile


async def get_owned_child(
    db: AsyncSession,
    model: type[T],
    row_id: int,
    current_user: User,
    *,
    not_found_detail: str,
    resource_name: str,
) -> tuple[T, Profile]:
    """
    Fetch a child row (task/project/calendar connection/...) by ID and
    authorize the caller against its owning profile.

    Backs each router's private `_get_<entity>_and_authorize` one-line
    wrapper (calendar connections, countdowns, integration connections, time
    entries, tasks, projects). The row's FK guarantees the profile exists, so
    only the row lookup gets a 404 - the profile itself is loaded via
    authorize_parent_profile, matching the child-resource shape everywhere
    else in this module.

    Args:
        db: The database session
        model: The ORM model class to fetch (must have a profile_id column)
        row_id: The row's ID
        current_user: The authenticated user
        not_found_detail: 404 detail to use when the row does not exist
        resource_name: Name of the resource for the 403 error message

    Returns:
        (row, profile) tuple - callers that only need the row discard profile

    Raises:
        HTTPException: 404 if the row does not exist, 403 if the caller is
        neither the profile's owner nor an admin
    """
    row = await db.get(model, row_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail
        )
    profile = await authorize_parent_profile(
        db, row.profile_id, current_user, resource_name
    )
    return row, profile


async def resolve_habit_profile_id(
    db: AsyncSession, owner_user_id: int, profile_id: int | None
) -> int:
    """Resolve the profile a habit should belong to.

    owner_user_id is the id of the user who owns (or will own) the habit. If
    profile_id is given, it must exist and belong to that owner (400
    otherwise) - this is what stops an admin editing someone else's habit
    from moving it into a profile that user doesn't own. If omitted, the
    owner's oldest profile is used for back-compat.

    Shared by the habits CRUD and the Loop Habit Tracker import.
    """
    if profile_id is not None:
        profile = await db.get(Profile, profile_id)
        if not profile or profile.user_id != owner_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile not found or does not belong to the habit's owner",
            )
        return profile_id

    result = await db.execute(
        select(Profile)
        .filter(Profile.user_id == owner_user_id)
        .order_by(Profile.created_date, Profile.id)
        .limit(1)
    )
    default_profile = result.scalar_one_or_none()
    if not default_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no profiles; create a profile first",
        )
    return default_profile.id


async def get_owned_habit(
    db: AsyncSession, habit_id: int, current_user: User
) -> tuple[Habit, Profile]:
    """
    Fetch a habit by ID and authorize the caller against its owning profile.

    A thin wrapper over get_owned_child, kept as a named helper because the
    habits and trackers routers both need the same 404 detail.

    Args:
        db: The database session
        habit_id: The ID of the habit to fetch
        current_user: The authenticated user

    Returns:
        (habit, profile) tuple - callers that only need the habit discard
        profile

    Raises:
        HTTPException: 404 if the habit does not exist, 403 if the caller is
        neither the owning profile's owner nor an admin
    """
    return await get_owned_child(
        db,
        Habit,
        habit_id,
        current_user,
        not_found_detail="Habit not found",
        resource_name="habit",
    )


def resolve_timezone(tz: str | None) -> ZoneInfo | None:
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


def resolve_today(tz: str | None) -> date:
    """
    Return "today" for an optional IANA timezone query parameter.

    datetime.now(None) is server-local time, so a missing tz keeps the
    legacy server-local behavior.

    Raises:
        HTTPException: 422 if the name is not a valid IANA timezone (see
        resolve_timezone)
    """
    return datetime.now(resolve_timezone(tz)).date()
