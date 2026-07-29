from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from habit_tracker.core.config import settings

echo = settings.sqlalchemy_echo

DATABASE_URL = settings.database_url

engine = create_async_engine(DATABASE_URL, echo=echo)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
