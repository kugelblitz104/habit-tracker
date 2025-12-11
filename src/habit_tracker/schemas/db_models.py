from datetime import date, datetime
from typing import List

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    habits: Mapped[List["Habit"]] = relationship(
        "Habit", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Habit(Base):
    __tablename__ = "habit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    range: Mapped[int] = mapped_column(Integer, nullable=False)
    reminder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="habits", lazy="selectin"
    )
    trackers: Mapped[List["Tracker"]] = relationship(
        "Tracker", back_populates="habit", cascade="all, delete-orphan", lazy="selectin"
    )


class Tracker(Base):
    __tablename__ = "tracker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    habit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("habit.id", ondelete="CASCADE"), nullable=False
    )
    dated: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    habit: Mapped["Habit"] = relationship(
        "Habit", back_populates="trackers", lazy="selectin"
    )

    # Constraints
    __table_args__ = (
        # Ensure one tracker per habit per date
        UniqueConstraint("habit_id", "dated", name="uix_habit_dated"),
    )
