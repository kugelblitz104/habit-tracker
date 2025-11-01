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

    logger.info(f"Creating access token with data: {data_to_encode}")
    logger.info(f"Using algorithm: {settings.algorithm}")

    token = jwt.encode(
        data_to_encode, settings.secret_key, algorithm=settings.algorithm
    )
    logger.info(f"Created token (first 20 chars): {token[:20]}...")
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
        logger.info(f"Decoding token (first 20 chars): {token[:20]}...")
        logger.info(f"Using algorithm: {settings.algorithm}")

        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        logger.info(f"Successfully decoded payload: {payload}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"Token decoding failed: {e}")
        return None
