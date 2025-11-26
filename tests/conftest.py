from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from habit_tracker.core.config import settings
from habit_tracker.core.dependencies import get_db
from habit_tracker.main import app
from habit_tracker.schemas.db_models import Base

# Use same database but different schema for tests
TEST_SCHEMA = "test"

# Track if shared schema is initialized (per test file)
_shared_schema_initialized = False


async def _setup_test_schema(engine: AsyncEngine, clean: bool = True) -> None:
    """Setup test schema, optionally cleaning all data.

    Args:
        engine: Database engine
        clean: If True, drops and recreates schema (fresh state)
               If False, only creates schema if missing (preserves data)
    """
    async with engine.begin() as conn:
        if clean:
            # Drop and recreate for complete isolation
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
            await conn.execute(CreateSchema(TEST_SCHEMA))
        else:
            # Only create if missing (preserves existing data)
            schema_exists = await conn.execute(
                text(f"SELECT 1 FROM pg_namespace WHERE nspname = '{TEST_SCHEMA}'")
            )
            if not schema_exists.scalar():
                await conn.execute(CreateSchema(TEST_SCHEMA))

        await conn.execute(text(f"SET search_path TO {TEST_SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture
async def shared_db_session() -> AsyncIterator[AsyncSession]:
    """Database session that shares data across tests in the same test run.

    The schema is created once on first use and preserved across all tests
    using this fixture. Data created in one test will be visible in subsequent
    tests. Great for workflow/integration tests.

    Example:
        async def test_01_create_user(shared_db_session):
            user = User(username="test")
            shared_db_session.add(user)
            await shared_db_session.commit()

        async def test_02_find_user(shared_db_session):
            # User from test_01 still exists
            result = await shared_db_session.execute(select(User))
            assert result.scalar_one()
    """
    global _shared_schema_initialized

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )

    try:
        # Only setup schema once for all shared tests
        if not _shared_schema_initialized:
            await _setup_test_schema(engine, clean=True)
            _shared_schema_initialized = True

        async_session = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with async_session() as session:
            await session.execute(text(f"SET search_path TO {TEST_SCHEMA}"))
            await session.commit()
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Database session with complete isolation - fresh schema for each test.

    This is the default fixture that provides maximum test isolation. Each test
    gets a completely clean database with no data from previous tests.

    Use this fixture (default) when you want each test to be independent.

    Example:
        async def test_create_user(db_session):
            # Always starts with empty database
            user = User(username="test")
            db_session.add(user)
            await db_session.commit()

        async def test_another(db_session):
            # Fresh database again, no users exist
            result = await db_session.execute(select(User))
            assert result.scalars().all() == []
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )

    try:
        # Drop and recreate schema for complete isolation
        await _setup_test_schema(engine, clean=True)

        async_session = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with async_session() as session:
            await session.execute(text(f"SET search_path TO {TEST_SCHEMA}"))
            await session.commit()
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Test client with isolated database session (fresh for each test).

    Use this with the default db_session fixture for isolated API tests.
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def shared_client(shared_db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Test client with shared database session (data persists across tests).

    Use this with shared_db_session fixture for workflow/integration tests
    where you want API calls to build on data from previous tests.
    """

    async def override_get_db():
        yield shared_db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
