import logging
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from habit_tracker.database import SessionLocal
from habit_tracker.schemas.db_models import User
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: int = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
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
