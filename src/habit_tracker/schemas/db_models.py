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
from habit_tracker.constants import TaskStatus, TimeEntryKind, TrackerStatus


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
    countdowns_enabled: Mapped[bool] = mapped_column(
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
    week_start_monday: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    use_habit_color_accent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Per-profile pomodoro timer defaults (minutes, and pomodoros before a long
    # break). The frontend timer reads these; individual runs may still override.
    pomodoro_work_minutes: Mapped[int] = mapped_column(
        Integer, default=25, nullable=False
    )
    pomodoro_break_minutes: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    pomodoro_long_break_minutes: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )
    pomodoro_cycles: Mapped[int] = mapped_column(
        Integer, default=4, nullable=False
    )
    # Whether the estimated-effort field is shown on tasks in this profile.
    show_estimated_effort: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
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
    calendar_connections: Mapped[List["CalendarConnection"]] = relationship(
        "CalendarConnection",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="select",
    )
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="select",
    )
    integration_connections: Mapped[List["IntegrationConnection"]] = relationship(
        "IntegrationConnection",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="select",
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
    # Adhoc time entries attached directly to the project. Also detached (not
    # deleted) when the project is removed (ON DELETE SET NULL).
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry", back_populates="project", passive_deletes=True, lazy="select"
    )


class CalendarConnection(Base):
    __tablename__ = "calendar_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ICS feed cache - internal, never exposed via the API
    cached_ics: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    etag: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="calendar_connections", lazy="select"
    )


class IntegrationConnection(Base):
    """A per-profile connection to an external task tracker (Azure DevOps or
    GitHub), authenticated with a user-supplied PAT stored encrypted. Which
    provider-specific columns are used depends on `provider`:
    - azure_devops: `organization` + `project` (required), `work_item_type`
      (optional publish type, defaults to "Task"), `base_url` (optional host
      root for on-prem Azure DevOps Server / TFS; defaults to the public cloud
      `https://dev.azure.com`).
    - github: `default_repo` ("owner/repo", the publish target; reading assigned
      issues needs no repo).
    """

    __tablename__ = "integration_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Fernet-encrypted PAT - internal, never exposed via the API.
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    # Azure DevOps: organization + project. GitHub: unused.
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    project: Mapped[str | None] = mapped_column(String, nullable=True)
    work_item_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Azure DevOps: optional host root for on-prem Azure DevOps Server / TFS
    # (e.g. "https://tfs.example.com"); NULL means the public cloud. GitHub: unused.
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # GitHub: "owner/repo" publish target. Azure DevOps: unused.
    default_repo: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="integration_connections", lazy="select"
    )

    @property
    def has_token(self) -> bool:
        """Whether a PAT is stored (surfaced by the API; the token never is)."""
        return bool(self.encrypted_token)


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
    # Self-referential parent for subtasks - ONE level deep only (a subtask
    # can never itself have subtasks; enforced in the router, not the DB).
    # Deleting a parent deletes its subtasks (ON DELETE CASCADE).
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[int] = mapped_column(
        Integer, default=TaskStatus.OPEN, nullable=False
    )
    block_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # External work-item link. `source` is the provider ("azure_devops" /
    # "github") or NULL for tasks with no external origin; `external_ref` is the
    # human key (e.g. "AB#2841", "owner/repo#42"); `external_url` deep-links to
    # the item. The unique constraint below makes sync idempotent (re-syncing an
    # already-imported item is a no-op) without blocking multiple purely-local
    # tasks, since NULLs compare distinct in Postgres.
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Estimated level of effort in minutes (est-vs-actual against time entries).
    estimated_effort: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Manual display order among siblings (ascending). Used for drag-to-reorder
    # subtasks; ties (and never-reordered tasks, all 0) fall back to created_date.
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, index=True
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="tasks", lazy="select"
    )
    project: Mapped["Project | None"] = relationship(
        "Project", back_populates="tasks", lazy="select"
    )
    # Subtask deletion rides on the DB's ON DELETE CASCADE (passive_deletes),
    # so the ORM never needs to load children to delete a parent
    subtasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="parent",
        passive_deletes=True,
        lazy="select",
    )
    parent: Mapped["Task | None"] = relationship(
        "Task", back_populates="subtasks", remote_side="Task.id", lazy="select"
    )
    # Time entries ride on the DB's ON DELETE CASCADE (passive_deletes), so
    # deleting a task never needs to load its entries first
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry",
        back_populates="task",
        passive_deletes=True,
        lazy="select",
    )

    # Constraints
    __table_args__ = (
        # One task per (profile, provider, external ref) so re-syncing an
        # imported item never duplicates it. Purely-local tasks have NULL
        # source/external_ref, which Postgres treats as distinct, so this never
        # constrains manually-created tasks.
        UniqueConstraint(
            "profile_id",
            "source",
            "external_ref",
            name="uix_task_profile_source_external_ref",
        ),
    )


class TimeEntry(Base):
    __tablename__ = "time_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable so a timer can run untethered to any task; deleting the task
    # deletes its time entries (ON DELETE CASCADE).
    task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Direct project attachment for "adhoc" work not tied to a task. Mutually
    # exclusive with task_id (a task-attached entry's project is derived from
    # its task). Deleting the project just detaches (ON DELETE SET NULL).
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[int] = mapped_column(
        Integer, default=TimeEntryKind.STOPWATCH, nullable=False
    )
    # Optional free-text label ("Standup", "Code review", …); autofilled from
    # recent entries in the UI.
    label: Mapped[str | None] = mapped_column(String, default=None, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    # Null while the timer is running; set when stopped.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Elapsed seconds, computed on stop; null while running.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile", back_populates="time_entries", lazy="select"
    )
    task: Mapped["Task | None"] = relationship(
        "Task", back_populates="time_entries", lazy="select"
    )
    project: Mapped["Project | None"] = relationship(
        "Project", back_populates="time_entries", lazy="select"
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


class Countdown(Base):
    __tablename__ = "countdown"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a task. A countdown is a first-class entity: it can stand
    # alone (no task) or reference one for context/navigation. Deleting the task
    # unlinks the countdown (SET NULL) rather than deleting it, since its target
    # date is its own.
    task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("task.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    # The countdown's own target (prefilled from a linked task's due date, then
    # independent). Date is required; time is optional (date-only = end of day).
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    # Free-text grouping label (e.g. "Birthdays", "Bills") + an optional hex
    # accent — both drive the grouped/colored countdown views.
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    # Recurrence: none/weekly/monthly/yearly. target_date is the anchor; the next
    # occurrence is derived from it (birthdays roll to next year, bills to next
    # month) — no server-side rollover job.
    repeat: Mapped[str] = mapped_column(String, default="none", nullable=False)
    # Opt-in: show the Nth occurrence for a recurring countdown (e.g. "26th
    # birthday"), derived client-side from the anchor.
    show_occurrence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile", lazy="select")
    task: Mapped["Task | None"] = relationship("Task", lazy="select")
