import logging
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from habit_tracker.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def create_access_token(
    data: dict,
    expires_delta: timedelta = timedelta(minutes=settings.access_token_expiry_minutes),
):
    data_to_encode = data.copy()

    data_to_encode.update(
        {"exp": datetime.now(timezone.utc) + expires_delta, "type": "access"}
    )

    logger.debug("Creating access token")

    token = jwt.encode(
        data_to_encode, settings.secret_key, algorithm=settings.algorithm
    )
    return token


def create_refresh_token(data: dict):
    data_to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expiry_days
    )

    data_to_encode.update({"exp": expire, "type": "refresh"})

    return jwt.encode(data_to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str):
    try:
        logger.debug("Decoding token")

        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Token decoding failed: {str(e)}")
        return None
