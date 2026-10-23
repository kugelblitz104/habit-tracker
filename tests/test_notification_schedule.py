"""Every write that can move a reminder leaves the right `scheduled_notification` row.

The rules themselves (which instant) are pinned in test_notifications.py; this
file pins the wiring: each write path recomputes its entity's row, and the
in-memory wake-up fires only after the transaction that wrote the row commits.
The profile zone is America/New_York with every trigger on, unless a test says
otherwise.
"""

import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import event, select, update

from habit_tracker.constants import TaskStatus
from habit_tracker.core.clock import utc_now
from habit_tracker.schemas.db_models import Habit, ScheduledNotification
from habit_tracker.services import notifications
from habit_tracker.services.notifications import (
    CONFIG,
    COUNTDOWN,
    HABIT,
    JOURNAL,
    TASK,
    next_habit_fire,
    poke,
    reschedule,
    to_utc,
)
from tests.conftest import engine
from tests.factories import (
    CountdownFactory,
    HabitFactory,
    ProfileFactory,
    ProjectFactory,
    TaskFactory,
    UserFactory,
)
from tests.test_imports import build_loop_db, upload

NY = "America/New_York"
LA = "America/Los_Angeles"
DUE = date.today() + timedelta(days=30)


def due_fire(day: date = DUE, at: time = time(9, 0), zone: str = NY) -> datetime:
    """The first default reminder (60 min before) of a task due `day` at `at`."""
    return to_utc(day, at, ZoneInfo(zone)) - timedelta(minutes=60)


async def make_profile(db_session, **overrides):
    user = UserFactory(default_profile=False)
    fields = {
        "timezone": NY,
        "notify_task_due": True,
        "notify_task_scheduled": True,
        "notify_habits": True,
        "notify_countdowns": True,
        "notify_journal": True,
    }
    profile = ProfileFactory(user=user, **{**fields, **overrides})
    await db_session.commit()
    return user, profile


async def rows(db_session) -> dict[tuple[str, int], tuple[int, datetime]]:
    """Every schedule row as {(entity_type, entity_id): (profile_id, fire_at)}."""
    result = await db_session.execute(select(ScheduledNotification))
    return {
        (r.entity_type, r.entity_id): (r.profile_id, r.fire_at)
        for r in result.scalars()
    }


class TestTaskWrites:
    async def test_create_schedules(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)

        response = await client.post(
            "/tasks/",
            json={"profile_id": profile.id, "title": "Pay rent", "due_date": str(DUE)},
        )

        task_id = response.json()["id"]
        assert await rows(db_session) == {(TASK, task_id): (profile.id, due_fire())}

    async def test_patch_moves_the_time(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()

        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})

        assert await rows(db_session) == {
            (TASK, task.id): (profile.id, due_fire(at=time(17, 0)))
        }

    async def test_patch_clearing_the_date_deletes(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})

        await client.patch(f"/tasks/{task.id}", json={"due_date": None})

        assert await rows(db_session) == {}

    async def test_closing_deletes(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})

        await client.patch(f"/tasks/{task.id}", json={"status": TaskStatus.DONE.value})

        assert await rows(db_session) == {}

    async def test_custom_offsets_move_the_time(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()

        await client.patch(f"/tasks/{task.id}", json={"due_reminder_offsets": [1440]})

        assert await rows(db_session) == {
            (TASK, task.id): (
                profile.id,
                to_utc(DUE, time(9, 0), ZoneInfo(NY)) - timedelta(days=1),
            )
        }

    async def test_moving_to_another_profile_updates_the_row(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        other = ProfileFactory(
            user=user, timezone=LA, notify_task_due=True, name="Other"
        )
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})

        await client.patch(f"/tasks/{task.id}", json={"profile_id": other.id})

        assert await rows(db_session) == {
            (TASK, task.id): (other.id, due_fire(at=time(17, 0), zone=LA))
        }

    async def test_delete_removes_the_row(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        created = await client.post(
            "/tasks/",
            json={"profile_id": profile.id, "title": "Pay rent", "due_date": str(DUE)},
        )

        await client.delete(f"/tasks/{created.json()['id']}")

        assert await rows(db_session) == {}


class TestHabitWrites:
    async def test_create_schedules(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)

        response = await client.post(
            "/habits/",
            json={
                "profile_id": profile.id,
                "name": "Stretch",
                "question": "Did you stretch?",
                "color": "#112233",
                "frequency": 1,
                "range": 1,
                "reminder": True,
                "reminder_time": "08:00:00",
            },
        )

        habit = await db_session.get(Habit, response.json()["id"])
        expected = next_habit_fire(habit, profile, utc_now())
        assert expected is not None
        assert await rows(db_session) == {(HABIT, habit.id): (profile.id, expected)}

    async def test_patch_turning_the_reminder_off_deletes(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        await login_as(user)
        habit = HabitFactory(
            profile=profile, reminder=True, reminder_time=time(8, 0), reminder_days=127
        )
        await db_session.commit()
        await client.patch(f"/habits/{habit.id}", json={"reminder_time": "09:00:00"})
        assert (HABIT, habit.id) in await rows(db_session)

        await client.patch(f"/habits/{habit.id}", json={"reminder": False})

        assert await rows(db_session) == {}

    async def test_archiving_deletes(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        habit = HabitFactory(
            profile=profile, reminder=True, reminder_time=time(8, 0), reminder_days=127
        )
        await db_session.commit()
        await client.patch(f"/habits/{habit.id}", json={"reminder_time": "09:00:00"})

        await client.patch(f"/habits/{habit.id}", json={"archived": True})

        assert await rows(db_session) == {}

    async def test_delete_removes_the_row(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        habit = HabitFactory(
            profile=profile, reminder=True, reminder_time=time(8, 0), reminder_days=127
        )
        await db_session.commit()
        await client.patch(f"/habits/{habit.id}", json={"reminder_time": "09:00:00"})

        await client.delete(f"/habits/{habit.id}")

        assert await rows(db_session) == {}

    async def test_loop_import_schedules(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        content = build_loop_db(
            habits=[
                {
                    "id": 1,
                    "name": "Read",
                    "reminder_hour": 7,
                    "reminder_min": 45,
                    "reminder_days": 127,
                }
            ],
            repetitions=[],
        )

        response = await client.post(
            "/import/loop-habit-tracker",
            files=upload(content),
            params={"profile_id": profile.id},
        )

        habit = await db_session.get(
            Habit, response.json()["details"][0]["new_habit_id"]
        )
        expected = next_habit_fire(habit, profile, utc_now())
        assert expected is not None
        assert await rows(db_session) == {(HABIT, habit.id): (profile.id, expected)}


class TestCountdownWrites:
    async def test_create_archive_and_delete(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)

        created = await client.post(
            "/countdowns/",
            json={
                "profile_id": profile.id,
                "title": "Trip",
                "target_date": str(DUE),
                "target_time": "10:00:00",
            },
        )
        countdown_id = created.json()["id"]
        fire = to_utc(DUE, time(10, 0), ZoneInfo(NY))
        assert await rows(db_session) == {(COUNTDOWN, countdown_id): (profile.id, fire)}

        await client.patch(f"/countdowns/{countdown_id}", json={"archived": True})
        assert await rows(db_session) == {}

        await client.patch(f"/countdowns/{countdown_id}", json={"archived": False})
        assert (COUNTDOWN, countdown_id) in await rows(db_session)

        await client.delete(f"/countdowns/{countdown_id}")
        assert await rows(db_session) == {}

    async def test_moving_to_another_profile_updates_the_row(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        other = ProfileFactory(
            user=user, timezone=LA, notify_countdowns=True, name="Other"
        )
        await login_as(user)
        countdown = CountdownFactory(
            profile=profile, target_date=DUE, target_time=time(10, 0)
        )
        await db_session.commit()
        await client.patch(f"/countdowns/{countdown.id}", json={"title": "Trip"})

        await client.patch(f"/countdowns/{countdown.id}", json={"profile_id": other.id})

        assert await rows(db_session) == {
            (COUNTDOWN, countdown.id): (
                other.id,
                to_utc(DUE, time(10, 0), ZoneInfo(LA)),
            )
        }


class TestProfileWrites:
    async def test_toggle_on_builds_every_row(self, client, db_session, login_as):
        user, profile = await make_profile(
            db_session,
            notify_task_due=False,
            notify_countdowns=False,
            notify_journal=False,
            journal_enabled=True,
            journal_prompt_time=time(21, 0),
        )
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        countdown = CountdownFactory(
            profile=profile, target_date=DUE, target_time=time(10, 0)
        )
        await db_session.commit()
        assert await rows(db_session) == {}

        await client.patch(
            f"/profiles/{profile.id}",
            json={
                "notify_task_due": True,
                "notify_countdowns": True,
                "notify_journal": True,
            },
        )

        found = await rows(db_session)
        assert found[(TASK, task.id)] == (profile.id, due_fire())
        assert found[(COUNTDOWN, countdown.id)] == (
            profile.id,
            to_utc(DUE, time(10, 0), ZoneInfo(NY)),
        )
        assert found[(JOURNAL, profile.id)][0] == profile.id
        assert len(found) == 3

    async def test_toggle_off_removes_the_rows(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        TaskFactory(profile=profile, due_date=DUE)
        CountdownFactory(profile=profile, target_date=DUE)
        await db_session.commit()
        await client.patch(f"/profiles/{profile.id}", json={"notify_task_due": True})
        assert await rows(db_session)

        await client.patch(
            f"/profiles/{profile.id}",
            json={
                "notify_task_due": False,
                "notify_task_scheduled": False,
                "notify_countdowns": False,
                "notify_journal": False,
            },
        )

        assert await rows(db_session) == {}

    async def test_timezone_change_recomputes(self, client, db_session, login_as):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/profiles/{profile.id}", json={"timezone": NY})
        assert (await rows(db_session))[(TASK, task.id)][1] == due_fire()

        await client.patch(f"/profiles/{profile.id}", json={"timezone": LA})

        assert (await rows(db_session))[(TASK, task.id)][1] == due_fire(zone=LA)

    async def test_create_with_journal_on_schedules_the_journal(
        self, client, db_session, login_as
    ):
        user = UserFactory(default_profile=False)
        await db_session.commit()
        await login_as(user)

        response = await client.post(
            "/profiles/",
            json={
                "name": "Fresh",
                "timezone": NY,
                "notify_journal": True,
                "journal_enabled": True,
                "journal_prompt_time": "21:00:00",
            },
        )

        profile_id = response.json()["id"]
        assert list(await rows(db_session)) == [(JOURNAL, profile_id)]

    async def test_a_bad_stored_zone_schedules_nothing(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session, timezone="Not/AZone")
        await login_as(user)
        TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()

        response = await client.patch(
            f"/profiles/{profile.id}", json={"notify_task_due": True}
        )

        assert response.status_code == 200
        assert await rows(db_session) == {}


class TestProjectMove:
    async def test_tasks_follow_the_project_to_the_new_profile(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        other = ProfileFactory(
            user=user, timezone=LA, notify_task_due=True, name="Other"
        )
        await login_as(user)
        project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile, project=project, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})

        await client.patch(f"/projects/{project.id}", json={"profile_id": other.id})

        assert await rows(db_session) == {
            (TASK, task.id): (other.id, due_fire(at=time(17, 0), zone=LA))
        }


class TestBackupImport:
    async def test_import_builds_the_rows(self, client, db_session, login_as):
        user, profile = await make_profile(
            db_session, journal_enabled=True, journal_prompt_time=time(21, 0)
        )
        await login_as(user)
        TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        export = (await client.get(f"/backup/profiles/{profile.id}")).json()
        assert await rows(db_session) == {}

        response = await client.post("/backup/profiles", json=export)

        new_id = response.json()["profile_id"]
        found = await rows(db_session)
        assert {(t, p) for (t, _), (p, _) in found.items()} == {
            (TASK, new_id),
            (JOURNAL, new_id),
        }


class TestPoke:
    async def test_only_an_earlier_time_wakes(self, monkeypatch):
        monkeypatch.setattr(notifications, "_next_at", None)
        notifications._wake.clear()
        noon = datetime(2030, 1, 1, 12)

        poke(noon)
        assert notifications._next_at == noon
        assert notifications._wake.is_set()

        notifications._wake.clear()
        poke(noon + timedelta(hours=1))
        assert notifications._next_at == noon
        assert not notifications._wake.is_set()

        poke(noon - timedelta(hours=1))
        assert notifications._next_at == noon - timedelta(hours=1)
        assert notifications._wake.is_set()

    async def test_poke_waits_for_the_commit(self, db_session, monkeypatch):
        monkeypatch.setattr(notifications, "_next_at", None)
        _, profile = await make_profile(db_session)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.flush()

        await reschedule(db_session, TASK, task)
        assert notifications._next_at is None

        await db_session.commit()
        assert notifications._next_at == due_fire()

    async def test_rollback_discards_the_pending_poke(self, db_session, monkeypatch):
        monkeypatch.setattr(notifications, "_next_at", None)
        _, profile = await make_profile(db_session)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.flush()

        await reschedule(db_session, TASK, task)
        await db_session.rollback()
        await db_session.commit()

        assert notifications._next_at is None
        assert await rows(db_session) == {}


class TestProjectMoveStaleRows:
    async def test_task_with_nothing_to_fire_in_the_new_profile_loses_its_row(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        other = ProfileFactory(
            user=user, timezone=LA, notify_task_due=False, name="Other"
        )
        await login_as(user)
        project = ProjectFactory(profile=profile)
        task = TaskFactory(profile=profile, project=project, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})
        assert (TASK, task.id) in await rows(db_session)

        await client.patch(f"/projects/{project.id}", json={"profile_id": other.id})

        assert await rows(db_session) == {}


class TestRebuildChunking:
    async def test_a_profile_larger_than_one_chunk_is_rebuilt_whole(
        self, client, db_session, login_as, monkeypatch
    ):
        monkeypatch.setitem(CONFIG["scheduler"], "upsert_chunk", 2)
        user, profile = await make_profile(
            db_session, notify_task_due=False, notify_journal=False
        )
        await login_as(user)
        tasks = [TaskFactory(profile=profile, due_date=DUE) for _ in range(5)]
        await db_session.commit()
        inserts: list[str] = []

        def count(conn, cursor, statement, *_):
            if statement.startswith("INSERT INTO scheduled_notification"):
                inserts.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            response = await client.patch(
                f"/profiles/{profile.id}", json={"notify_task_due": True}
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)

        assert response.status_code == 200
        assert {key for key in await rows(db_session)} == {(TASK, t.id) for t in tasks}
        assert len(inserts) == math.ceil(len(tasks) / 2)


class TestProfilePatchScope:
    async def test_a_rename_leaves_the_schedule_alone(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})
        sentinel = utc_now() + timedelta(days=400)
        await db_session.execute(update(ScheduledNotification).values(fire_at=sentinel))
        await db_session.commit()

        await client.patch(f"/profiles/{profile.id}", json={"name": "Renamed"})

        assert await rows(db_session) == {(TASK, task.id): (profile.id, sentinel)}

    async def test_a_timezone_change_still_recomputes(
        self, client, db_session, login_as
    ):
        user, profile = await make_profile(db_session)
        await login_as(user)
        task = TaskFactory(profile=profile, due_date=DUE)
        await db_session.commit()
        await client.patch(f"/tasks/{task.id}", json={"due_time": "17:00:00"})
        await db_session.execute(
            update(ScheduledNotification).values(fire_at=utc_now())
        )
        await db_session.commit()

        await client.patch(f"/profiles/{profile.id}", json={"timezone": LA})

        assert await rows(db_session) == {
            (TASK, task.id): (profile.id, due_fire(at=time(17, 0), zone=LA))
        }
