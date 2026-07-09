from datetime import date, datetime, time
from typing import List

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from habit_tracker.constants import TaskStatus, TrackerStatus


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
        "Habit", back_populates="user", cascade="all, delete-orphan", lazy="select"
    )
    profiles: Mapped[List["Profile"]] = relationship(
        "Profile", back_populates="user", cascade="all, delete-orphan", lazy="select"
    )


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color_start: Mapped[str] = mapped_column(
        String, default="#e0763f", nullable=False
    )
    color_end: Mapped[str] = mapped_column(String, default="#c14e6a", nullable=False)
    habits_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    calendar_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    publish_to_azure: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    default_landing: Mapped[str] = mapped_column(
        String, default="today", nullable=False
    )
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="profiles", lazy="select"
    )
    habits: Mapped[List["Habit"]] = relationship(
        "Habit", back_populates="profile", cascade="all, delete-orphan", lazy="select"
    )
    projects: Mapped[List["Project"]] = relationship(
        "Project",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="select",
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="profile", cascade="all, delete-orphan", lazy="select"
    )

    # Constraints
    __table_args__ = (
        # Ensure profile names are unique per user
        UniqueConstraint("user_id", "name", name="uix_profile_user_name"),
    )


class Habit(Base):
    __tablename__ = "habit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
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
    user: Mapped["User"] = relationship("User", back_populates="habits", lazy="select")
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="habits", lazy="select"
    )
    trackers: Mapped[List["Tracker"]] = relationship(
        "Tracker", back_populates="habit", cascade="all, delete-orphan", lazy="select"
    )


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="projects", lazy="select"
    )
    # Tasks are not deleted with their project - the DB sets task.project_id
    # to NULL (ON DELETE SET NULL), so no delete-orphan cascade here
    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="project", passive_deletes=True, lazy="select"
    )


class Task(Base):
    __tablename__ = "task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[int] = mapped_column(
        Integer, default=TaskStatus.OPEN, nullable=False
    )
    block_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)
    closed_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="tasks", lazy="select"
    )
    project: Mapped["Project | None"] = relationship(
        "Project", back_populates="tasks", lazy="select"
    )


class Tracker(Base):
    __tablename__ = "tracker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    habit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("habit.id", ondelete="CASCADE"), nullable=False
    )
    dated: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    status: Mapped[int] = mapped_column(
        Integer, default=TrackerStatus.COMPLETED, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    habit: Mapped["Habit"] = relationship(
        "Habit", back_populates="trackers", lazy="select"
    )

    # Constraints
    __table_args__ = (
        # Ensure one tracker per habit per date
        UniqueConstraint("habit_id", "dated", name="uix_habit_dated"),
    )
