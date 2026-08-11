# Habit Tracker API

FastAPI REST API behind a personal productivity app: habits and streaks, tasks and projects,
time tracking, countdowns, calendar feeds and external task-tracker integrations. Async
SQLAlchemy on PostgreSQL, Pydantic v2, Alembic, managed with `uv`.

The React front-end lives in the sibling [habit-tracker-front-end](https://github.com/kugelblitz104/habit-tracker-front-end)
repo and generates its entire API client from this service's OpenAPI schema, so the two are
developed together.

## Features

- **Users and profiles** — a user owns one or more profiles, and nearly every entity is
  profile-scoped. Each profile carries its own colours, feature toggles (habits, countdowns,
  insights, calendar), default landing page, week start, and pomodoro defaults.
- **Habits and trackers** — daily tracking with not-completed / skipped / completed states,
  "N times per M days" frequencies, server-side auto-skip, and manual sort order.
- **Habit stats** — streaks, completion rates and weekday breakdowns, timezone-aware via a
  `tz` query param.
- **Tasks** — statuses, priorities, due and scheduled dates, one level of subtasks, computed
  urgency bands (now / soon / whenever / hidden), manual sort, and Markdown export.
- **Projects** — group tasks, with open/done counts on the read model.
- **Time tracking** — stopwatch and pomodoro entries attributed to a task or project, with a
  running-entry endpoint and a grouped summary. Subtask time rolls up to the parent's project.
- **Countdowns** — recurring or one-off target dates, grouped into colour-owning categories.
- **Calendar** — ICS feeds fetched, parsed and expanded into dated events.
- **Integrations** — Azure DevOps (cloud and on-prem) and GitHub, with per-profile PATs
  encrypted at rest, task sync, and publish.
- **Backup and import** — full-profile export/import as a single JSON document, plus a Loop
  Habit Tracker importer.
- **Auth** — JWT access and refresh tokens, password reset by email (SMTP, provider-agnostic).
- **Readable URLs** — tasks, projects and habits each carry a server-assigned `slug` and a
  `GET /…/by-slug/{slug}` route.

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | FastAPI |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy (async, asyncpg) |
| Migrations | Alembic |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | PyJWT, Passlib + bcrypt |
| Encryption | `cryptography` (Fernet) for integration secrets |
| Calendar | icalendar + recurring-ical-events |
| Email | aiosmtplib |
| Tests | pytest, pytest-asyncio, pytest-xdist, factory_boy |
| Lint / format | basedpyright, ruff |
| Package manager | uv (Python 3.11+) |

## Getting Started

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 16 (or use the compose stack below)
- [uv](https://github.com/astral-sh/uv)

### Installation

```bash
uv sync                 # runtime + test dependencies
uv sync --all-groups    # also installs the dev group (ruff, basedpyright)
```

`uv sync --group dev` *replaces* the default group selection and uninstalls pytest with it —
use `--all-groups`.

### Environment Variables

Create a `.env` file in the project root. Everything has a working default except
`DATABASE_URL`.

```env
DATABASE_URL=postgresql+asyncpg://habit_tracker:dev_password@localhost:5432/habit_tracker_dev
SECRET_KEY=your-secret-key-here
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string (asyncpg driver) |
| `SECRET_KEY` | dev placeholder | JWT signing key |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRY_MINUTES` | `30` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRY_DAYS` | `7` | Refresh-token lifetime |
| `RESET_TOKEN_EXPIRY_MINUTES` | `30` | Password-reset link lifetime |
| `CORS_ORIGINS` | empty | Comma-separated allowed origins. Any localhost port is allowed regardless, for the Vite dev server |
| `SQLALCHEMY_ECHO` | `false` | Log emitted SQL |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | blank / `587` | Password-reset email delivery. With `SMTP_HOST` blank the reset link is logged instead of sent, so the flow works offline |
| `RESET_URL_BASE` | `http://localhost:3000/reset-password` | Front-end page the emailed reset link points at |
| `INTEGRATION_ENCRYPTION_KEY` | derived from `SECRET_KEY` | Fernet key for encrypting integration PATs. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Rotating `SECRET_KEY` while this is blank invalidates stored PATs |

### Run the local stack

Postgres plus the API in containers. The API container mounts `./src` with `--reload` and runs
`alembic upgrade head` on start, so backend edits reload live and `/openapi.json` updates
immediately.

```bash
podman compose up -d     # or: docker compose up -d
podman compose logs -f
podman compose down
```

Container names are `habit_tracker_db` and `habit_tracker_api`.

### Run without a container

Needs a reachable Postgres.

```bash
uv run alembic upgrade head
uv run uvicorn habit_tracker.main:app --reload --port 8080
```

- API: <http://localhost:8080>
- Docs: <http://localhost:8080/docs>
- OpenAPI schema: <http://localhost:8080/openapi.json>

## Tests

The suite needs Postgres up. Each pytest-xdist worker creates its own schema (`test_gw0`,
`test_gw1`, …) in the dev database and every test runs inside a transaction rolled back at
teardown, so nothing persists.

```bash
uv run pytest                                             # full suite, serial
uv run pytest -n auto                                     # parallel
uv run pytest tests/test_tasks.py                         # one file
uv run pytest tests/test_tasks.py::TestListTasks::test_x  # one test
```

`tests/test_habit_stats.py` is pure arithmetic with in-memory objects — no database, no
fixtures. It also runs a **KPI parity harness** against the front-end: the shared case table
lives in the sibling repo at `src/test-support/kpi-parity-cases.json`, located via the
`KPI_PARITY_CASES` env var. If that repo isn't checked out the parity tests skip with an
explicit message.

## Lint and Format

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run basedpyright
```

All three are clean; a finding is one you introduced. Four rule families are disabled in
`pyproject.toml` with the reasoning inline — read those comments before re-enabling anything.

## Migrations

```bash
uv run alembic revision --autogenerate -m "Description of changes"
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic history
```

## The OpenAPI schema is effectively frozen

The front-end generates its whole API client from `/openapi.json`, so any schema change breaks
it. Before and after touching `models/` or a router, diff the schema — `app.openapi()` needs no
database:

```bash
OA='import json,sys;from habit_tracker.main import app;print(json.dumps(app.openapi(),indent=2,sort_keys=("s" in sys.argv[1:])))'
.venv/Scripts/python.exe -c "$OA" s > before.sorted.json   # order-insensitive
.venv/Scripts/python.exe -c "$OA"   > before.raw.json      # also catches property reordering
```

Both diffs must be empty. If a break is deliberate, regenerate the client in the same change
(`npm run generate-api` in the front-end, with this API on :8080) and append new properties
**last** so existing positional arguments in the generated client don't shift.

## Docker

```bash
docker build -t habit-tracker-api:latest .
docker run -p 8080:8080 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  -e SECRET_KEY=your-secret-key \
  habit-tracker-api:latest
```

Two Dockerfiles: the plain `Dockerfile` for deployment and CI, and `Dockerfile.zscaler` for
local builds behind a corporate TLS proxy. The latter takes the CA as a build secret; compose
supplies it from `ZSCALER_CA_PATH` and falls back to `/dev/null` when that's unset.

## Project Structure

```text
src/habit_tracker/
├── main.py                 # FastAPI app; every router registers here
├── database.py             # Async engine and session
├── constants.py            # Enums + compute_band()
├── core/
│   ├── config.py           # pydantic-settings
│   ├── dependencies.py     # Auth and ownership helpers
│   ├── http.py             # Shared response/error shapes
│   ├── security.py         # Hashing and JWTs
│   ├── crypto.py           # Fernet encryption for integration PATs
│   ├── slugs.py            # Slug generation and lookup
│   └── email.py            # SMTP delivery
├── models/                 # Pydantic request/response models, one per entity
├── routers/                # auth, users, profiles, projects, tasks, time_entries,
│                           # habits, trackers, countdowns, countdown_categories,
│                           # calendar_connections, integrations, imports, backup
├── schemas/db_models.py    # Every SQLAlchemy table
└── services/               # habit_stats, calendar_events, profile_backup,
                            # task_export, countdown_categories, loop_format,
                            # integrations/

alembic/versions/           # Migrations
tests/                      # pytest suite + factories
```

**Two model layers — don't conflate them.** `schemas/db_models.py` is SQLAlchemy; `models/` is
Pydantic. Routers convert with `SomeRead.model_validate(orm_row)`, and `models/__init__.py`
never re-exports ORM classes (a test locks this).

**Ownership helpers are the backbone.** `core/dependencies.py` holds `get_current_user`,
`get_owned_profile`, `get_owned_child`, `authorize_parent_profile` and friends. Reuse them
rather than reimplementing 404/403 checks in a router.

## API Endpoints

Every list endpoint caps `limit` at 100. Clients that filter in memory must page.

**Auth** — `POST /auth/{register,login,refresh,forgot-password,reset-password}`

**Users** — `GET /users/`, `GET /users/me`, `GET|PUT|PATCH|DELETE /users/{user_id}`

**Profiles** — `GET|POST /profiles/`, `GET|PATCH|DELETE /profiles/{profile_id}`

**Projects** — `GET|POST|DELETE /projects/`, `GET /projects/by-slug/{slug}`,
`GET|PATCH|DELETE /projects/{project_id}`

**Tasks** — `GET|POST|DELETE /tasks/`, `GET /tasks/export`, `PUT /tasks/sort`,
`GET /tasks/by-slug/{slug}`, `GET|PATCH|DELETE /tasks/{task_id}`

**Time entries** — `GET|POST|DELETE /time-entries/`, `GET /time-entries/active`,
`GET /time-entries/summary`, `POST /time-entries/{entry_id}/stop`,
`GET|PATCH|DELETE /time-entries/{entry_id}`

**Habits** — `GET|POST|DELETE /habits/`, `PUT /habits/sort`, `GET /habits/by-slug/{slug}`,
`GET|PUT|PATCH|DELETE /habits/{habit_id}`, plus `/habits/{habit_id}/{trackers,trackers/lite,kpis,streaks}`

**Trackers** — `POST|DELETE /trackers/`, `GET|PUT|PATCH|DELETE /trackers/{tracker_id}`

**Countdowns** — `GET|POST|DELETE /countdowns/`, `GET|PATCH|DELETE /countdowns/{countdown_id}`,
and the same shape under `/countdown-categories/`

**Calendar** — `GET|POST /calendar-connections/`, `GET /calendar-connections/events`,
`GET|PATCH|DELETE /calendar-connections/{connection_id}`

**Integrations** — `GET|POST /integrations/`, `GET|PATCH|DELETE /integrations/{connection_id}`,
`POST /integrations/{connection_id}/{sync,publish}`

**Backup and import** — `GET /backup/profiles/{profile_id}`, `POST /backup/profiles`,
`GET|POST /import/loop-habit-tracker`

The `DELETE` on a collection route is a bulk delete scoped to one profile.

## Related Projects

- [Habit Tracker Front-End](https://github.com/kugelblitz104/habit-tracker-front-end) — React web interface

## License

This project is private and not licensed for public use.
