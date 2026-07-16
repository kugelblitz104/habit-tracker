from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.core.config import settings
from habit_tracker.core.dependencies import get_db
from habit_tracker.core.email import send_password_reset_email
from habit_tracker.core.security import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from habit_tracker.models.users import (
    ForgotPasswordRequest,
    MessageResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
)
from habit_tracker.schemas.db_models import Profile, User

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    # Check if user exists
    preexisting_user_ = await db.execute(
        select(User).filter(User.email == user_data.email)
    )
    preexisting_user = preexisting_user_.scalar_one_or_none()
    if preexisting_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    preexisting_user_ = await db.execute(
        select(User).filter(User.username == user_data.username)
    )
    preexisting_user = preexisting_user_.scalar_one_or_none()
    if preexisting_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.plaintext_password)
    new_user = User(
        username=user_data.username,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email=user_data.email,
        password_hash=hashed_password,
    )

    db.add(new_user)
    await db.flush()  # assign new_user.id before creating the default profile

    # Every user needs at least one profile - create the default "Personal"
    # profile in the same transaction (mirrors the migration backfill)
    default_profile = Profile(user_id=new_user.id, name="Personal")
    db.add(default_profile)

    await db.commit()
    await db.refresh(new_user)

    # Generate tokens
    access_token = create_access_token(data={"sub": str(new_user.id)})
    refresh_token = create_refresh_token(data={"sub": str(new_user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    OAuth2 compatible token login, get an access token for future requests.

    Use username (or email) and password to login.
    The username field accepts either username or email.
    """
    # The OAuth2 "username" field accepts either the username or the email —
    # both columns are unique, so a single OR lookup resolves the account.
    identifier = form_data.username
    user = await db.execute(
        select(User).filter(
            (User.username == identifier) | (User.email == identifier)
        )
    )
    user = user.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    payload = decode_token(request.refresh_token)

    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = await db.execute(select(User).filter(User.id == int(user_id)))
    user = user.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user"
        )

    new_access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Begin a password reset.

    Always returns the same response whether or not the email is registered, so
    the endpoint can't be used to enumerate accounts. When a matching user
    exists, a short-lived reset link is emailed (or logged, in dev) in the
    background so the response time doesn't reveal whether an account was found.
    """
    result = await db.execute(select(User).filter(User.email == request.email))
    user = result.scalar_one_or_none()

    if user:
        reset_token = create_reset_token(data={"sub": str(user.id)})
        reset_link = f"{settings.reset_url_base}?token={reset_token}"
        background_tasks.add_task(send_password_reset_email, user.email, reset_link)

    return {
        "message": (
            "If an account exists for that email, a password reset link has "
            "been sent."
        )
    }


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Complete a password reset using the token from the emailed link.

    The token is a stateless JWT with ``type == "reset"``; a bad/expired/
    wrong-type token all yield the same generic 400 so nothing is leaked. The
    ~30-minute expiry bounds the window in which a leaked link is usable.
    """
    payload = decode_token(request.token)

    if payload is None or payload.get("type") != "reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    result = await db.execute(select(User).filter(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = get_password_hash(request.new_password)
    user.updated_date = datetime.now()
    await db.commit()

    return {"message": "Your password has been reset. You can now sign in."}
