"""Tests for the Loop Habit Tracker import/export endpoints."""

import base64
import os
import sqlite3
import tempfile
from datetime import UTC, date, datetime, time

from sqlalchemy import select

from habit_tracker.constants import TrackerStatus
from habit_tracker.routers.imports import mask_from_loop, mask_to_loop
from habit_tracker.schemas.db_models import Habit, Tracker
from tests.factories import (
    HabitFactory,
    ProfileFactory,
    TrackerFactory,
    UserFactory,
)


def loop_timestamp(day: date) -> int:
    """Milliseconds since epoch at midnight UTC — Loop's repetition format."""
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def timestamp_to_day(timestamp_ms: int) -> date:
    """Decode a Loop repetition timestamp (midnight-UTC ms) to its date."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()


def read_export_rows(payload: dict, query: str) -> list[sqlite3.Row]:
    """Decode the base64 export into a temp SQLite db and run a query on it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(payload["data"]))
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(query).fetchall()
        finally:
            conn.close()
    finally:
        os.unlink(path)


def build_loop_db(habits: list[dict], repetitions: list[dict]) -> bytes:
    """Build a minimal Loop Habit Tracker SQLite database as raw bytes.

    habits: dicts with id/name (+ optional archived, color, description,
    freq_den, freq_num, position, question, reminder_hour, reminder_min,
    reminder_days).
    repetitions: dicts with habit/timestamp/value (+ optional notes).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE Habits (
                id INTEGER PRIMARY KEY,
                archived INTEGER,
                color INTEGER,
                description TEXT,
                freq_den INTEGER,
                freq_num INTEGER,
                name TEXT,
                position INTEGER,
                question TEXT,
                reminder_hour INTEGER,
                reminder_min INTEGER,
                reminder_days INTEGER NOT NULL DEFAULT 127
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE Repetitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                value INTEGER NOT NULL,
                notes TEXT
            )
            """
        )
        for h in habits:
            cursor.execute(
                "INSERT INTO Habits (id, archived, color, description, freq_den,"
                " freq_num, name, position, question, reminder_hour, reminder_min,"
                " reminder_days)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    h["id"],
                    h.get("archived", 0),
                    h.get("color", 0),
                    h.get("description"),
                    h.get("freq_den", 1),
                    h.get("freq_num", 1),
                    h["name"],
                    h.get("position", 0),
                    h.get("question", ""),
                    h.get("reminder_hour"),
                    h.get("reminder_min"),
                    h.get("reminder_days", 127),
                ),
            )
        for r in repetitions:
            cursor.execute(
                "INSERT INTO Repetitions (habit, timestamp, value, notes)"
                " VALUES (?, ?, ?, ?)",
                (r["habit"], r["timestamp"], r["value"], r.get("notes")),
            )
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


async def login(client, user) -> None:
    response = await client.post(
        "/auth/login",
        data={"username": user.username, "password": "password123"},
    )
    client.headers.update(
        {"Authorization": f"Bearer {response.json()['access_token']}"}
    )


def upload(content: bytes, filename: str = "loop.db") -> dict:
    return {"file": (filename, content, "application/octet-stream")}


class TestImportFromLoopHabitTracker:
    """Tests for POST /import/loop-habit-tracker."""

    async def test_import_defaults_to_oldest_profile(self, client, db_session):
        """Without profile_id, habits land in the user's default profile."""
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        content = build_loop_db(
            habits=[{"id": 1, "name": "Meditate"}],
            repetitions=[
                {"habit": 1, "timestamp": loop_timestamp(date(2025, 6, 1)), "value": 2}
            ],
        )
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["habits_imported"] == 1
        assert data["trackers_imported"] == 1

        habit = await db_session.get(Habit, data["details"][0]["new_habit_id"])
        assert habit.profile_id == user.profiles[0].id

    async def test_import_into_explicit_profile(self, client, db_session):
        """profile_id targets a specific profile and sort_order appends there."""
        user = UserFactory()
        second_profile = ProfileFactory(user=user)
        existing = HabitFactory(user=user, profile=second_profile, sort_order=7)
        await db_session.commit()
        await login(client, user)

        content = build_loop_db(
            habits=[{"id": 1, "name": "Read"}, {"id": 2, "name": "Stretch"}],
            repetitions=[],
        )
        response = await client.post(
            "/import/loop-habit-tracker",
            params={"profile_id": second_profile.id},
            files=upload(content),
        )
        assert response.status_code == 201
        assert response.json()["habits_imported"] == 2

        result = await db_session.execute(
            select(Habit)
            .where(Habit.profile_id == second_profile.id, Habit.id != existing.id)
            .order_by(Habit.sort_order)
        )
        imported = result.scalars().all()
        assert [h.profile_id for h in imported] == [second_profile.id] * 2
        # Appended after the profile's existing max sort_order
        assert [h.sort_order for h in imported] == [8, 9]

    async def test_import_rejects_foreign_profile(self, client, db_session):
        """Importing into another user's profile is a 400."""
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login(client, user)

        content = build_loop_db(habits=[{"id": 1, "name": "Nope"}], repetitions=[])
        response = await client.post(
            "/import/loop-habit-tracker",
            params={"profile_id": other.profiles[0].id},
            files=upload(content),
        )
        assert response.status_code == 400

    async def test_import_preserves_full_history(self, client, db_session):
        """Repetitions years in the past import with exact dates (UTC decode)."""
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        old_days = [date(2019, 5, 4), date(2021, 12, 31), date(2024, 2, 29)]
        content = build_loop_db(
            habits=[{"id": 1, "name": "Journal"}],
            repetitions=[
                {"habit": 1, "timestamp": loop_timestamp(d), "value": 2}
                for d in old_days
            ],
        )
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 201
        data = response.json()
        assert data["trackers_imported"] == len(old_days)

        result = await db_session.execute(
            select(Tracker.dated)
            .join(Habit, Tracker.habit_id == Habit.id)
            .where(Habit.id == data["details"][0]["new_habit_id"])
            .order_by(Tracker.dated)
        )
        assert list(result.scalars().all()) == old_days

    async def test_import_maps_loop_values_to_status(self, client, db_session):
        """0 not imported; 1 and 3 -> SKIPPED; 2 and numeric -> COMPLETED."""
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        cases = {
            date(2025, 1, 1): 0,  # not done: dropped
            date(2025, 1, 2): 1,  # old-style skip
            date(2025, 1, 3): 2,  # done
            date(2025, 1, 4): 3,  # Loop 2.x skip
            date(2025, 1, 5): 5000,  # numerical habit amount x 1000
        }
        content = build_loop_db(
            habits=[{"id": 1, "name": "Hydrate"}],
            repetitions=[
                {"habit": 1, "timestamp": loop_timestamp(d), "value": v}
                for d, v in cases.items()
            ],
        )
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 201
        data = response.json()
        assert data["trackers_imported"] == 4
        assert data["trackers_skipped"] == 1

        result = await db_session.execute(
            select(Tracker.dated, Tracker.status)
            .join(Habit, Tracker.habit_id == Habit.id)
            .where(Habit.id == data["details"][0]["new_habit_id"])
        )
        statuses = {row.dated: row.status for row in result}
        assert date(2025, 1, 1) not in statuses
        assert statuses[date(2025, 1, 2)] == TrackerStatus.SKIPPED
        assert statuses[date(2025, 1, 3)] == TrackerStatus.COMPLETED
        assert statuses[date(2025, 1, 4)] == TrackerStatus.SKIPPED
        assert statuses[date(2025, 1, 5)] == TrackerStatus.COMPLETED

    async def test_import_dedupes_same_day_repetitions(self, client, db_session):
        """Two repetitions on the same date keep only the first."""
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        day = date(2025, 3, 10)
        content = build_loop_db(
            habits=[{"id": 1, "name": "Walk"}],
            repetitions=[
                {"habit": 1, "timestamp": loop_timestamp(day), "value": 2},
                {"habit": 1, "timestamp": loop_timestamp(day) + 1, "value": 2},
            ],
        )
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 201
        assert response.json()["trackers_imported"] == 1
        assert response.json()["trackers_skipped"] == 1

    async def test_import_rejects_wrong_extension(self, client, db_session):
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        response = await client.post(
            "/import/loop-habit-tracker", files=upload(b"junk", filename="habits.csv")
        )
        assert response.status_code == 400

    async def test_import_rejects_non_loop_database(self, client, db_session):
        """A valid SQLite file without Loop's tables is a 400."""
        user = UserFactory()
        await db_session.commit()
        await login(client, user)

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE Unrelated (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            # Tiny local temp-file read in test setup, alongside the equally
            # blocking sqlite3 calls above - not worth threaded/async I/O.
            with open(path, "rb") as f:  # noqa: ASYNC230
                content = f.read()
        finally:
            os.unlink(path)

        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 400
        assert "Habits" in response.json()["detail"]

    async def test_import_requires_auth(self, client, db_session):
        content = build_loop_db(habits=[], repetitions=[])
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 401


class TestExportToLoopHabitTracker:
    """Tests for GET /import/loop-habit-tracker."""

    async def test_export_filters_by_profile(self, client, db_session):
        """profile_id exports only that profile's habits."""
        user = UserFactory()
        second_profile = ProfileFactory(user=user)
        HabitFactory(user=user, name="First profile habit")
        HabitFactory(user=user, profile=second_profile, name="Second profile habit")
        await db_session.commit()
        await login(client, user)

        response = await client.get(
            "/import/loop-habit-tracker", params={"profile_id": second_profile.id}
        )
        assert response.status_code == 200

        rows = read_export_rows(response.json(), "SELECT name FROM Habits")
        assert [r["name"] for r in rows] == ["Second profile habit"]

    async def test_export_rejects_foreign_profile(self, client, db_session):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login(client, user)

        response = await client.get(
            "/import/loop-habit-tracker", params={"profile_id": other.profiles[0].id}
        )
        assert response.status_code == 403

    async def test_export_writes_loop2_skip_values(self, client, db_session):
        """SKIPPED exports as Loop 2.x's 3; COMPLETED as 2."""
        user = UserFactory()
        habit = HabitFactory(user=user)
        TrackerFactory(habit=habit, dated=date(2025, 4, 1))
        TrackerFactory(
            habit=habit, dated=date(2025, 4, 2), status=TrackerStatus.SKIPPED
        )
        await db_session.commit()
        await login(client, user)

        response = await client.get("/import/loop-habit-tracker")
        assert response.status_code == 200

        rows = read_export_rows(
            response.json(), "SELECT timestamp, value FROM Repetitions"
        )
        values = {timestamp_to_day(r["timestamp"]): r["value"] for r in rows}
        assert values[date(2025, 4, 1)] == 2
        assert values[date(2025, 4, 2)] == 3

    async def test_export_import_round_trip(self, client, db_session):
        """An exported file imports back with identical dates and statuses."""
        user = UserFactory()
        target_profile = ProfileFactory(user=user)
        habit = HabitFactory(user=user, name="Round trip", color="#1976D2")
        TrackerFactory(habit=habit, dated=date(2023, 11, 5))
        TrackerFactory(
            habit=habit, dated=date(2024, 8, 20), status=TrackerStatus.SKIPPED
        )
        await db_session.commit()
        await login(client, user)

        export_response = await client.get("/import/loop-habit-tracker")
        assert export_response.status_code == 200
        content = base64.b64decode(export_response.json()["data"])

        import_response = await client.post(
            "/import/loop-habit-tracker",
            params={"profile_id": target_profile.id},
            files=upload(content),
        )
        assert import_response.status_code == 201
        data = import_response.json()
        assert data["habits_imported"] == 1
        assert data["trackers_imported"] == 2

        result = await db_session.execute(
            select(Tracker.dated, Tracker.status)
            .join(Habit, Tracker.habit_id == Habit.id)
            .where(Habit.id == data["details"][0]["new_habit_id"])
            .order_by(Tracker.dated)
        )
        rows = list(result)
        assert [(r.dated, r.status) for r in rows] == [
            (date(2023, 11, 5), TrackerStatus.COMPLETED),
            (date(2024, 8, 20), TrackerStatus.SKIPPED),
        ]


# Loop's bit order: 0 = Saturday, 1 = Sunday, 2 = Monday ... 6 = Friday.
# Ours: 0 = Monday ... 6 = Sunday.
LOOP_BIT_TO_OURS = {0: 5, 1: 6, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4}


class TestLoopWeekdayMask:
    def test_each_single_day_maps_both_ways(self):
        for loop_bit, our_bit in LOOP_BIT_TO_OURS.items():
            assert mask_from_loop(1 << loop_bit) == 1 << our_bit
            assert mask_to_loop(1 << our_bit) == 1 << loop_bit

    def test_every_day_is_every_day(self):
        assert mask_from_loop(127) == 127
        assert mask_to_loop(127) == 127

    def test_empty_loop_mask_means_every_day(self):
        """Loop coerces an empty day set to every day."""
        assert mask_from_loop(0) == 127

    def test_round_trips_every_mask(self):
        for mask in range(1, 128):
            assert mask_from_loop(mask_to_loop(mask)) == mask


class TestLoopReminders:
    async def _import(self, client, db_session, login_as, habit: dict) -> Habit:
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        content = build_loop_db(
            habits=[{"id": 1, "name": "Read", **habit}], repetitions=[]
        )
        response = await client.post(
            "/import/loop-habit-tracker", files=upload(content)
        )
        assert response.status_code == 201
        return await db_session.get(
            Habit, response.json()["details"][0]["new_habit_id"]
        )

    async def test_import_carries_the_reminder(self, client, db_session, login_as):
        # Loop Mon + Wed = bits 2 and 4.
        habit = await self._import(
            client,
            db_session,
            login_as,
            {"reminder_hour": 7, "reminder_min": 45, "reminder_days": 0b10100},
        )

        assert habit.reminder is True
        assert habit.reminder_time == time(7, 45)
        assert habit.reminder_days == 0b101  # Mon + Wed

    async def test_import_without_a_reminder(self, client, db_session, login_as):
        habit = await self._import(client, db_session, login_as, {})

        assert habit.reminder is False
        assert habit.reminder_time is None
        assert habit.reminder_days == 127

    async def test_import_treats_an_out_of_range_hour_as_off(
        self, client, db_session, login_as
    ):
        habit = await self._import(
            client, db_session, login_as, {"reminder_hour": 25, "reminder_min": 0}
        )

        assert habit.reminder is False
        assert habit.reminder_time is None

    async def test_export_writes_the_reminder(self, client, db_session, login_as):
        user = UserFactory()
        HabitFactory(
            user=user, reminder=True, reminder_time=time(21, 5), reminder_days=0b1
        )
        await db_session.commit()
        await login_as(user)

        response = await client.get("/import/loop-habit-tracker")

        row = read_export_rows(
            response.json(),
            "SELECT reminder_hour, reminder_min, reminder_days FROM Habits",
        )[0]
        assert (row["reminder_hour"], row["reminder_min"]) == (21, 5)
        assert row["reminder_days"] == 1 << 2  # Monday, in Loop's order

    async def test_export_writes_null_when_off(self, client, db_session, login_as):
        """Loop reads a non-null hour as "on", so an off reminder must be NULL,
        not the midnight-on-no-days 0/0/0 the export used to write."""
        user = UserFactory()
        HabitFactory(user=user, reminder=False, reminder_time=time(9, 0))
        HabitFactory(user=user, reminder=True, reminder_time=None)
        await db_session.commit()
        await login_as(user)

        response = await client.get("/import/loop-habit-tracker")

        rows = read_export_rows(
            response.json(),
            "SELECT reminder_hour, reminder_min, reminder_days FROM Habits",
        )
        assert len(rows) == 2
        for row in rows:
            assert row["reminder_hour"] is None
            assert row["reminder_min"] is None
            assert row["reminder_days"] == 127

    async def test_reminder_round_trips(self, client, db_session, login_as):
        user = UserFactory()
        target = ProfileFactory(user=user)
        HabitFactory(
            user=user, reminder=True, reminder_time=time(6, 0), reminder_days=0b1100000
        )
        await db_session.commit()
        await login_as(user)

        exported = await client.get("/import/loop-habit-tracker")
        imported = await client.post(
            "/import/loop-habit-tracker",
            params={"profile_id": target.id},
            files=upload(base64.b64decode(exported.json()["data"])),
        )
        habit = await db_session.get(
            Habit, imported.json()["details"][0]["new_habit_id"]
        )

        assert habit.reminder is True
        assert habit.reminder_time == time(6, 0)
        assert habit.reminder_days == 0b1100000  # Sat + Sun
