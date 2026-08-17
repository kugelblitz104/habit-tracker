"""Seed the local dev database with representative data for every entity type.

Drives the real HTTP API rather than the ORM, so slugs, the countdown category
mirror and every validator run exactly as they do for the front-end.

    uv run python scripts/seed_dev_data.py --username admin123 --password secret

Re-running resets the target profile first, so the end state is the same every
time. Pass --keep to add another batch instead.

Dates are derived from --anchor-date (default today), so the Today and Insights
surfaces always have current data. Everything else is drawn from a fixed RNG
seed, making two runs with the same anchor identical.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta

import httpx

RNG_SEED = 20260817
DEFAULT_BASE_URL = "http://127.0.0.1:8080"

# Bulk-delete order. Children first, so a delete never depends on a cascade
# firing. Calendar connections and integrations have no bulk route and are
# handled separately.
RESET_PATHS = (
    "/time-entries/",
    "/trackers/",
    "/tasks/",
    "/countdowns/",
    "/countdown-categories/",
    "/habits/",
    "/projects/",
)
# Paths with no bulk route, paired with the key their list response uses. Every
# *List model keys its collection by entity name rather than "items", and the
# name is not derivable from the path (/integrations/ -> integration_connections).
RESET_BY_ID_PATHS = (
    ("/calendar-connections/", "calendar_connections"),
    ("/integrations/", "integration_connections"),
)

CATEGORIES = (
    ("Personal", "#4f9d69"),
    ("Work", "#c14e6a"),
)

PROJECTS = (
    ("Home Renovation", "#e0763f", "Kitchen first, then the back bedroom.", False),
    ("Habit Tracker API", "#4f9d69", "Backend work for the tracker.", False),
    ("Reading List", "#5b8def", None, False),
    ("Tax Year 2025", "#8b8b8b", "Closed out in April.", True),
)

# (title, project index, priority, status, due offset, scheduled offset, effort)
# Covers all nine TaskStatus values and all four TaskPriority values, plus
# overdue / today / soon / far / undated.
TASKS = (
    ("Replace kitchen tap", 0, 3, 1, -2, None, 60),
    ("Get quotes for flooring", 0, 2, 0, 3, None, 30),
    ("Choose paint colours", 0, 1, 4, None, 5, None),
    ("Clear the loft", 0, 0, 5, None, None, 240),
    ("Add countdown category colours", 1, 3, 6, -9, None, 90),
    ("Page the task list endpoint", 1, 2, 1, 0, None, 120),
    ("Write the seed script", 1, 2, 8, 1, None, 45),
    ("Investigate podman port binding", 1, 1, 3, 7, None, None),
    ("Retire the countdown colour column", 1, 0, 7, None, None, 30),
    ("Finish Piranesi", 2, 1, 0, 14, None, 180),
    ("Start The Bee Sting", 2, 0, 2, None, 21, None),
    ("Return library books", 2, 3, 0, -1, None, 15),
)

# (parent task index, title, priority, status)
SUBTASKS = (
    (0, "Buy tap fittings", 2, 6),
    (0, "Turn the mains off", 3, 0),
    (1, "Measure the hallway", 1, 0),
    (5, "Add the parent_id filter", 2, 6),
    (5, "Walk the pages client-side", 2, 1),
)

# (name, question, colour, frequency, range, category)
HABITS = (
    ("Morning run", "Did I run today?", "#e0763f", 1, 1, "Health"),
    ("Read 20 pages", "Did I read today?", "#5b8def", 1, 1, "Mind"),
    ("Gym", "Did I train this week?", "#4f9d69", 3, 7, "Health"),
    ("Deep clean", "Did I deep clean this month?", "#c14e6a", 1, 30, None),
)

# Per-habit chance a given day gets a COMPLETED tracker, and the chance a day
# has no row at all. Varied so the KPI and streak surfaces are non-trivial.
HABIT_COMPLETION = (0.82, 0.65, 0.45, 0.30)
HABIT_GAP = (0.05, 0.15, 0.25, 0.40)
TRACKER_DAYS = 60
FORCED_STREAK_DAYS = 6


class SeedError(RuntimeError):
    """A request the seeder made was rejected."""


class Seeder:
    """Creates one profile's worth of dev data over the HTTP API."""

    def __init__(
        self,
        client: httpx.Client,
        profile_id: int,
        anchor: date,
        rng: random.Random,
    ) -> None:
        self.client = client
        self.profile_id = profile_id
        self.anchor = anchor
        self.rng = rng
        self.counts: dict[str, int] = {}

    # --- request helpers ---

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise SeedError(
                f"{method} {path} -> {response.status_code}: {response.text[:400]}"
            )
        return response

    def _post(self, path: str, payload: dict) -> dict:
        payload = {"profile_id": self.profile_id, **payload}
        return self._request("POST", path, json=payload).json()

    def _get(self, path: str, **params) -> dict:
        params = {"profile_id": self.profile_id, **params}
        return self._request("GET", path, params=params).json()

    # --- reset ---

    def reset(self) -> None:
        """Delete everything in the target profile."""
        for path in RESET_PATHS:
            self._request("DELETE", path, params={"profile_id": self.profile_id})
        for path, key in RESET_BY_ID_PATHS:
            for row in self._get(path)[key]:
                self._request("DELETE", f"{path}{row['id']}")

    # --- seeding ---

    def seed(self) -> dict[str, int]:
        categories = self._seed_categories()
        projects = self._seed_projects()
        tasks = self._seed_tasks(projects)
        subtasks = self._seed_subtasks(tasks)
        self._seed_time_entries(tasks, subtasks, projects)
        habits = self._seed_habits()
        self._seed_trackers(habits)
        self._seed_countdowns(categories, tasks)
        self._seed_calendar_connection()
        self._seed_integrations()
        return self.counts

    def _seed_categories(self) -> list[int]:
        ids = [
            self._post("/countdown-categories/", {"name": name, "color": color})["id"]
            for name, color in CATEGORIES
        ]
        self.counts["countdown_categories"] = len(ids)
        return ids

    def _seed_projects(self) -> list[int]:
        ids = []
        for name, color, notes, archived in PROJECTS:
            payload = {"name": name, "color": color, "archived": archived}
            if notes is not None:
                payload["notes"] = notes
            ids.append(self._post("/projects/", payload)["id"])
        self.counts["projects"] = len(ids)
        return ids

    def _seed_tasks(self, projects: list[int]) -> list[int]:
        ids = []
        for index, row in enumerate(TASKS):
            title, project_index, priority, status, due, scheduled, effort = row
            payload: dict = {
                "title": title,
                "project_id": projects[project_index],
                "priority": priority,
                "status": status,
                "sort_order": index,
            }
            if due is not None:
                payload["due_date"] = (self.anchor + timedelta(days=due)).isoformat()
            if scheduled is not None:
                payload["scheduled_date"] = (
                    self.anchor + timedelta(days=scheduled)
                ).isoformat()
            if effort is not None:
                payload["estimated_effort"] = effort
            if status == 3:
                payload["block_reason"] = "Waiting on the supplier to confirm stock"
            # The source / external_ref / external_url triple is validated as a
            # unit, so all three go on together or none do.
            if title == "Page the task list endpoint":
                payload["source"] = "github"
                payload["external_ref"] = "kugelblitz104/habit-tracker#412"
                payload["external_url"] = (
                    "https://github.com/kugelblitz104/habit-tracker/issues/412"
                )
            if index == 5:
                payload["due_time"] = time(17, 0).isoformat()
            ids.append(self._post("/tasks/", payload)["id"])
        self.counts["tasks"] = len(ids)
        return ids

    def _seed_subtasks(self, tasks: list[int]) -> list[int]:
        ids = []
        for parent_index, title, priority, status in SUBTASKS:
            ids.append(
                self._post(
                    "/tasks/",
                    {
                        "title": title,
                        "parent_id": tasks[parent_index],
                        "priority": priority,
                        "status": status,
                    },
                )["id"]
            )
        self.counts["subtasks"] = len(ids)
        return ids

    def _seed_time_entries(
        self, tasks: list[int], subtasks: list[int], projects: list[int]
    ) -> None:
        created = 0
        # Closed entries spread over the past fortnight.
        for offset in range(1, 13):
            day = self.anchor - timedelta(days=offset)
            start_hour = self.rng.randint(9, 16)
            minutes = self.rng.choice((25, 30, 45, 50, 75, 90))
            started = datetime.combine(day, time(start_hour, 0))
            self._post(
                "/time-entries/",
                {
                    "task_id": self.rng.choice(tasks),
                    "kind": 1 if minutes == 25 else 0,
                    "label": "Pomodoro" if minutes == 25 else None,
                    "started_at": started.isoformat(),
                    "ended_at": (started + timedelta(minutes=minutes)).isoformat(),
                },
            )
            created += 1

        # One on a subtask, so resolved_project_id shows the parent's project.
        subtask_start = datetime.combine(self.anchor - timedelta(days=1), time(11, 0))
        self._post(
            "/time-entries/",
            {
                "task_id": subtasks[3],
                "started_at": subtask_start.isoformat(),
                "ended_at": (subtask_start + timedelta(minutes=40)).isoformat(),
                "note": "Rolls up to the parent's project",
            },
        )
        created += 1

        # One against a project with no task at all.
        project_start = datetime.combine(self.anchor - timedelta(days=2), time(14, 30))
        self._post(
            "/time-entries/",
            {
                "project_id": projects[0],
                "label": "Site visit",
                "started_at": project_start.isoformat(),
                "ended_at": (project_start + timedelta(minutes=95)).isoformat(),
            },
        )
        created += 1

        # One left running for the active-timer surface.
        self._post(
            "/time-entries/",
            {
                "task_id": tasks[5],
                "label": "Current focus",
                "started_at": datetime.combine(self.anchor, time(9, 15)).isoformat(),
            },
        )
        created += 1

        self.counts["time_entries"] = created

    def _seed_habits(self) -> list[int]:
        ids = []
        for index, (name, question, color, frequency, rng_days, category) in enumerate(
            HABITS
        ):
            payload: dict = {
                "name": name,
                "question": question,
                "color": color,
                "frequency": frequency,
                "range": rng_days,
                "reminder": index == 0,
                "sort_order": index,
            }
            if category is not None:
                payload["category"] = category
            ids.append(self._post("/habits/", payload)["id"])
        self.counts["habits"] = len(ids)
        return ids

    def _seed_trackers(self, habits: list[int]) -> None:
        created = 0
        for index, habit_id in enumerate(habits):
            completion = HABIT_COMPLETION[index]
            gap = HABIT_GAP[index]
            for day_offset in range(TRACKER_DAYS):
                day = self.anchor - timedelta(days=day_offset)
                # Force a current streak on the first habit so the streak and
                # KPI surfaces have something to show.
                if index == 0 and day_offset < FORCED_STREAK_DAYS:
                    status = 2
                else:
                    if self.rng.random() < gap:
                        continue
                    roll = self.rng.random()
                    if roll < completion:
                        status = 2
                    elif roll < completion + 0.1:
                        status = 1
                    else:
                        status = 0
                self._request(
                    "POST",
                    "/trackers/",
                    json={
                        "habit_id": habit_id,
                        "dated": day.isoformat(),
                        "status": status,
                    },
                )
                created += 1
        self.counts["trackers"] = created

    def _seed_countdowns(self, categories: list[int], tasks: list[int]) -> None:
        rows: tuple[dict, ...] = (
            {
                "title": "Dentist appointment",
                "target_date": (self.anchor - timedelta(days=10)).isoformat(),
                "category_id": categories[0],
            },
            {
                "title": "Flooring delivery",
                "target_date": (self.anchor + timedelta(days=5)).isoformat(),
                "target_time": time(8, 30).isoformat(),
                "category_id": categories[1],
                "task_id": tasks[1],
            },
            {
                "title": "Sprint review",
                "target_date": (self.anchor + timedelta(days=3)).isoformat(),
                "category_id": categories[1],
                "repeat": "weekly",
                "show_occurrence": True,
            },
            {
                "title": "Wedding anniversary",
                "target_date": (self.anchor + timedelta(days=90)).isoformat(),
                "category_id": categories[0],
                "repeat": "yearly",
                "show_occurrence": True,
            },
        )
        for row in rows:
            self._post("/countdowns/", row)
        self.counts["countdowns"] = len(rows)

    def _seed_calendar_connection(self) -> None:
        self._post(
            "/calendar-connections/",
            {
                "name": "Work calendar",
                "color": "#5b8def",
                "url": "https://example.com/work-calendar.ics",
                "enabled": True,
            },
        )
        self.counts["calendar_connections"] = 1

    def _seed_integrations(self) -> None:
        # Tokens are placeholders. They are Fernet-encrypted on write and never
        # returned by a read schema, so nothing here reaches a real provider.
        self._post(
            "/integrations/",
            {
                "provider": "azure_devops",
                "name": "Internal ADO",
                "organization": "example-org",
                "project": "Habit Tracker",
                "work_item_type": "Task",
                "token": "seed-placeholder-ado-pat",
            },
        )
        self._post(
            "/integrations/",
            {
                "provider": "github",
                "name": "GitHub",
                "default_repo": "kugelblitz104/habit-tracker",
                "token": "seed-placeholder-github-pat",
            },
        )
        self.counts["integration_connections"] = 2


def login(client: httpx.Client, username: str, password: str) -> None:
    """Attach a bearer token for the given credentials."""
    response = client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    if response.status_code != 200:
        raise SeedError(
            f"login as {username!r} failed ({response.status_code}). "
            "Register the user first, or check --username/--password."
        )
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"


def resolve_profile(client: httpx.Client, profile_id: int | None) -> int:
    """Return the profile to seed, creating one if the user has none."""
    if profile_id is not None:
        return profile_id

    existing = client.get("/profiles/").json()["profiles"]
    if existing:
        return existing[0]["id"]

    created = client.post("/profiles/", json={"name": "Dev"})
    if created.status_code >= 400:
        raise SeedError(f"could not create a profile: {created.text[:400]}")
    return created.json()["id"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default=os.environ.get("SEED_USERNAME", "admin123"),
        help="account to seed (default: admin123, or SEED_USERNAME)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("SEED_PASSWORD"),
        help="that account's password (or SEED_PASSWORD)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SEED_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--profile-id",
        type=int,
        default=None,
        help="profile to seed (default: the account's first profile)",
    )
    parser.add_argument(
        "--anchor-date",
        type=date.fromisoformat,
        default=date.today(),
        help="date all relative dates hang off (default: today)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="add a batch instead of resetting the profile first",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.password:
        print(
            "error: no password given. Pass --password or set SEED_PASSWORD.",
            file=sys.stderr,
        )
        return 2

    try:
        with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
            login(client, args.username, args.password)
            profile_id = resolve_profile(client, args.profile_id)

            seeder = Seeder(
                client, profile_id, args.anchor_date, random.Random(RNG_SEED)
            )
            if not args.keep:
                print(f"resetting profile {profile_id} ...")
                seeder.reset()

            print(f"seeding profile {profile_id} (anchor {args.anchor_date}) ...")
            counts = seeder.seed()
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except httpx.ConnectError:
        print(
            f"error: could not reach {args.base_url}. Is the stack up?",
            file=sys.stderr,
        )
        return 1

    width = max(len(name) for name in counts)
    for name, count in counts.items():
        print(f"  {name.replace('_', ' '):<{width}}  {count:>4}")
    print(f"done. {sum(counts.values())} rows in profile {profile_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
