import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateSchema

from habit_tracker.core.config import settings
from habit_tracker.core.dependencies import get_db
from habit_tracker.main import app
from habit_tracker.schemas.db_models import Base
from tests.factories import (
    AdminUserFactory,
    CalendarConnectionFactory,
    DoneTaskFactory,
    HabitFactory,
    IntegrationConnectionFactory,
    ProfileFactory,
    ProjectFactory,
    RunningTimeEntryFactory,
    TaskFactory,
    TimeEntryFactory,
    TrackerFactory,
    UserFactory,
)

# Use the same database but a dedicated schema for tests.
# Under pytest-xdist each worker gets its own schema (test_gw0, test_gw1, ...)
# so parallel workers never touch each other's tables.
_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
TEST_SCHEMA = f"test_{_XDIST_WORKER}" if _XDIST_WORKER else "test"


def _test_database_url():
    """Build the test engine URL.

    On Windows, connecting to ``localhost`` costs ~2s per connection because
    asyncpg tries IPv6 (::1) first and has to time out before falling back to
    the IPv4 port published by the podman container. Pin to 127.0.0.1
    (~25ms per connection instead).
    """
    url = make_url(settings.database_url)
    if url.host in ("localhost",):
        url = url.set(host="127.0.0.1")
    return url


# One engine per pytest process (per xdist worker). Connections are pooled and
# reused across tests: the whole suite runs on a single session-scoped event
# loop (see asyncio_default_*_loop_scope in pyproject.toml), which is what
# makes pooling safe for asyncpg.
engine = create_async_engine(
    _test_database_url(),
    echo=False,
    pool_size=5,
    max_overflow=5,
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


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db_schema():
    """Create this worker's test schema once per session."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        await conn.execute(CreateSchema(TEST_SCHEMA))
        # search_path is already set per-connection via connect_args
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    await engine.dispose()


def _savepoint_sessionmaker(conn):
    return async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def db_session(setup_db_schema) -> AsyncIterator[AsyncSession]:
    """Isolated database session using transaction rollback.

    The test (and, via the ``client`` fixture's get_db override, the app under
    test) runs inside one outer transaction on a dedicated connection.
    ``session.commit()`` only releases a SAVEPOINT, so commits made by routers
    are visible to the test's assertions and vice versa, and everything is
    rolled back at teardown - no per-test DELETE/TRUNCATE round-trips needed.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with _savepoint_sessionmaker(conn)() as session:
            yield session
        if outer.is_active:
            await outer.rollback()


@pytest_asyncio.fixture(scope="class")
async def shared_db_session(setup_db_schema) -> AsyncIterator[AsyncSession]:
    """Database session that shares data across the tests of one class.

    Same rollback isolation as ``db_session`` but class-scoped: data created
    by one test remains visible to later tests in the same class (workflow
    tests) and is rolled back when the class finishes.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with _savepoint_sessionmaker(conn)() as session:
            yield session
        if outer.is_active:
            await outer.rollback()


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
    ProfileFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    HabitFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    ProjectFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    CalendarConnectionFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    IntegrationConnectionFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    TaskFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    DoneTaskFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    TimeEntryFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    RunningTimeEntryFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
    TrackerFactory._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]
