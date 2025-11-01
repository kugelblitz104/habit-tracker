import logging
from fastapi.security import HTTPBearer
from habit_tracker.database import SessionLocal

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


security = HTTPBearer()
