import os
import random
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from habit_tracker.schemas.db_models import Base, Habit, Tracker, User

echo = os.getenv("SQLALCHEMY_ECHO", "true").lower() == "true"
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=echo)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_db_and_tables(engine):
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.query(User).count() == 0:
            users = create_mock_users(random.randint(1, 5))
            for user in users:
                habits = create_mock_habits(user, random.randint(1, 3))
                for habit in habits:
                    create_mock_trackers(habit, random.randint(1, 5))


def create_mock_users(num_users: int = 1) -> list[User]:
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

    with SessionLocal() as session:
        session.add_all(users)
        session.commit()
        for user in users:
            session.refresh(user)
            print(f"Created user: {user.username} with ID: {user.id}")

    return users


def create_mock_habits(user: User, num_habits: int = 1):
    habits = [
        Habit(
            user=user,
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

    with SessionLocal() as session:
        session.add_all(habits)
        session.commit()
        for habit in habits:
            session.refresh(habit)
            print(
                f"Created habit: {habit.name} with ID: {habit.id} for user ID: {habit.user_id}"
            )

    return habits


def create_mock_trackers(habit: Habit, num_trackers: int = 1):
    trackers = [
        Tracker(
            habit=habit,
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

    with SessionLocal() as session:
        session.add_all(trackers)
        session.commit()
        for tracker in trackers:
            session.refresh(tracker)
            print(
                f"Created tracker for habit ID: {tracker.habit_id} on date: {tracker.dated}"
            )

    return trackers
