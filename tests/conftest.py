from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
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
from tests.factories import AdminUserFactory, HabitFactory, TrackerFactory, UserFactory

# Use same database but different schema for tests
TEST_SCHEMA = "test"


engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,
    connect_args={"server_settings": {"search_path": TEST_SCHEMA}},
)


@pytest.fixture(scope="session", autouse=True)
def fast_password_hashing():
    """Mock password hashing to be faster in tests."""
    from habit_tracker.core.security import pwd_context

    # Use md5_crypt for speed, but keep bcrypt for compatibility
    pwd_context.update(
        schemes=["md5_crypt", "bcrypt"], default="md5_crypt", deprecated="auto"
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_db_schema():
    """Create test schema once per session."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        await conn.execute(CreateSchema(TEST_SCHEMA))
        await conn.execute(text(f"SET search_path TO {TEST_SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    await engine.dispose()


async def _truncate_tables(session: AsyncSession):
    """Truncate all tables in the test schema."""
    # Get table names from metadata
    tables = [table.name for table in Base.metadata.sorted_tables]
    if not tables:
        return

    for table in tables:
        await session.execute(text(f'DELETE FROM "{table}"'))
    await session.commit()


@pytest_asyncio.fixture
async def db_session(setup_db_schema) -> AsyncIterator[AsyncSession]:
    """Database session with complete isolation - fresh schema for each test.

    Optimized to use TRUNCATE instead of DROP/CREATE SCHEMA.
    """
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        # Truncate tables to ensure clean state
        await _truncate_tables(session)

        yield session


@pytest_asyncio.fixture
async def shared_db_session(setup_db_schema) -> AsyncIterator[AsyncSession]:
    """Database session that shares data across tests.

    Does NOT truncate tables.
    """
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


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


@pytest.fixture
def setup_factories(db_session: AsyncSession) -> None:
    """Fixture to setup factories with the test database session."""

    # Set the session for all factories
    # type: ignore comments needed because Pylance doesn't recognize
    # SQLAlchemyModelFactory's extended FactoryOptions attributes
    UserFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    AdminUserFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    HabitFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    TrackerFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
