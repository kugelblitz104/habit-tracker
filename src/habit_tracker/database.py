import os
import random
import subprocess
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from habit_tracker.core.config import settings
from habit_tracker.schemas.db_models import Base, Habit, Tracker, User

echo = settings.sqlalchemy_echo

DATABASE_URL = settings.database_url

# SQLite-specific configuration
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(DATABASE_URL, echo=echo, connect_args=connect_args)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def fresh_start_db():
    """Drop all tables and recreate them"""
    print("Dropping and recreating all tables for a fresh start...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await create_mock_data()
    print("✓ Fresh start database setup complete")


async def create_db_and_tables(engine):
    """Create tables if they don't exist and optionally seed with data"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_mock_data():
    """Create mock data for testing"""
    users = await create_mock_users(random.randint(1, 5))
    for user in users:
        habits = await create_mock_habits(user, random.randint(1, 3))
        for habit in habits:
            await create_mock_trackers(habit, random.randint(1, 5))


async def create_mock_users(num_users: int = 1) -> list[User]:
    users = [
        User(
            username="johndoe",
            first_name="John",
            last_name="Doe",
            email="test@example.com",
            password_hash="hashed_password_example",  # TODO: Replace with actual hashed password
        )
    ]

    for i in range(1, num_users):
        users.append(
            User(
                username=f"user{i}",
                first_name=f"First{i}",
                last_name=f"Last{i}",
                email=f"email{i}@example.com",
                password_hash=f"hashed_password_example_{i}",
            )
        )

    async with SessionLocal() as session:
        session.add_all(users)
        await session.commit()
        for user in users:
            await session.refresh(user)
            print(f"Created user: {user.username} with ID: {user.id}")

    return users


async def create_mock_habits(user: User, num_habits: int = 1):
    habits = [
        Habit(
            user_id=user.id if user.id is not None else 1,
            name="Drink Water",
            question="Did you drink enough water today?",
            color="#00FF00",
            frequency=1,
            range=1,
            reminder=True,
            notes="Stay hydrated!",
        )
    ]

    for i in range(1, num_habits):
        habits.append(
            Habit(
                user_id=user.id if user.id is not None else 1,
                name=f"Habit{i}",
                question=f"Did you complete habit {i}?",
                color="#FF0000",
                frequency=1,
                range=7,
                reminder=False,
                notes=f"Notes for habit {i}",
            )
        )

    async with SessionLocal() as session:
        session.add_all(habits)
        await session.commit()
        for habit in habits:
            await session.refresh(habit)
            print(
                f"Created habit: {habit.name} with ID: {habit.id} for user ID: {habit.user_id}"
            )

    return habits


async def create_mock_trackers(habit: Habit, num_trackers: int = 1):
    trackers = [
        Tracker(
            habit_id=habit.id if habit.id is not None else 1,
            dated=datetime.now().date(),
            completed=True,
            skipped=False,
            note="Initial tracker note",
        )
    ]

    for i in range(1, num_trackers):
        trackers.append(
            Tracker(
                habit_id=habit.id if habit.id is not None else 1,
                dated=datetime.now().date() - timedelta(days=num_trackers - i),
                completed=True,
                skipped=(i % 2 == 0),  # Alternate between True and False
                note=f"Tracker note {i}",
            )
        )

    async with SessionLocal() as session:
        session.add_all(trackers)
        await session.commit()
        for tracker in trackers:
            await session.refresh(tracker)
            print(
                f"Created tracker for habit ID: {tracker.habit_id} on date: {tracker.dated}"
            )

    return trackers


async def init_db():
    """Initialize database tables"""
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Database initialized successfully")


async def reset_db():
    """Drop and recreate all tables"""
    response = input("⚠️  This will DELETE ALL DATA. Are you sure? (yes/no): ")
    if response.lower() != "yes":
        print("Cancelled.")
        return

    print("Dropping all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Database reset successfully")


async def seed_db():
    """Add mock data to database"""
    print("Seeding database with mock data...")
    await create_db_and_tables(engine)
    print("✓ Database seeded successfully")


async def backup_db():
    """Backup database (PostgreSQL only)"""
    # Parse DATABASE_URL from environment
    db_url = os.getenv("DATABASE_URL")
    if not db_url or "postgresql" not in db_url:
        print("❌ Only PostgreSQL backups are supported")
        return

    # Extract connection details
    # Format: postgresql://user:pass@host:port/dbname
    parts = db_url.replace("postgresql://", "").split("@")
    user_pass = parts[0].split(":")
    host_db = parts[1].split("/")
    host_port = host_db[0].split(":")

    user = user_pass[0]
    password = user_pass[1] if len(user_pass) > 1 else ""
    host = host_port[0]
    port = host_port[1] if len(host_port) > 1 else "5432"
    dbname = host_db[1]

    # Generate backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_{dbname}_{timestamp}.sql"

    # Set password environment variable
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    try:
        print(f"Backing up database to {backup_file}...")
        subprocess.run(
            [
                "pg_dump",
                "-h",
                host,
                "-p",
                port,
                "-U",
                user,
                "-d",
                dbname,
                "-f",
                backup_file,
            ],
            env=env,
            check=True,
        )
        print(f"✓ Backup saved to {backup_file}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Backup failed: {e}")
    except FileNotFoundError:
        print("❌ pg_dump not found. Install PostgreSQL client tools.")
