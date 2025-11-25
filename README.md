# Habit Tracker API

A FastAPI-based REST API for tracking habits with user authentication, habit management, and progress tracking.

## Features

- **User Authentication**: JWT-based authentication with secure password hashing
- **Habit Management**: Create, read, update, and delete habits
- **Habit Tracking**: Track habit completion over time
- **Admin Controls**: Admin user management capabilities
- **OpenAPI Documentation**: Auto-generated API documentation at `/docs`
- **Database Migrations**: Alembic for database schema management
- **Async Support**: Full async/await support with asyncpg

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL 16
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **Authentication**: JWT (PyJWT)
- **Password Hashing**: Passlib + bcrypt
- **Validation**: Pydantic v2
- **Package Manager**: uv
- **Python**: 3.11+

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 16 (or use Docker Compose)
- [uv](https://github.com/astral-sh/uv) package manager

## Getting Started

### Installation

Install dependencies using uv:

```bash
uv sync
```

### Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+asyncpg://habit_tracker:dev_password@localhost:5432/habit_tracker_dev
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Database Setup

Run migrations to set up the database schema:

```bash
uv run alembic upgrade head
```

### Development

Run the development server:

```bash
uv run uvicorn habit_tracker.main:app --reload --port 8080
```

The API will be available at `http://localhost:8080`

- **API Documentation**: <http://localhost:8080/docs>
- **OpenAPI Schema**: <http://localhost:8080/openapi.json>

## Docker Compose Support

Start all services (PostgreSQL + API) using Docker Compose:

```bash
docker-compose up -d
```

Or with Podman Compose:

```bash
podman compose up -d
```

Stop services:

```bash
docker-compose down
# or
podman compose down
```

View logs:

```bash
docker compose logs -f
# or
podman compose logs -f
```

### VS Code Tasks

The project includes VS Code tasks for Podman Compose:

- **Podman Compose Up**: Start services in detached mode
- **Podman Compose Down**: Stop and remove services
- **Podman Compose Logs**: Follow service logs
- **Podman Compose Restart**: Restart services

## Database Migrations

Create a new migration:

```bash
uv run alembic revision --autogenerate -m "Description of changes"
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Rollback last migration:

```bash
uv run alembic downgrade -1
```

View migration history:

```bash
uv run alembic history
```

## Docker Support

Build the Docker image:

```bash
docker build -t habit-tracker-api:latest .
```

Run the container:

```bash
docker run -p 8080:8080 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  -e SECRET_KEY=your-secret-key \
  habit-tracker-api:latest
```

Or with Podman:

```bash
podman build -t habit-tracker-api:latest .
podman run -p 8080:8080 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  -e SECRET_KEY=your-secret-key \
  habit-tracker-api:latest
```

## Project Structure

```
src/habit_tracker/
├── main.py                 # FastAPI application entry point
├── database.py             # Database connection and session
├── core/
│   ├── config.py           # Settings and configuration
│   ├── dependencies.py     # Dependency injection
│   └── security.py         # Authentication and security
├── models/                 # Pydantic models
├── routers/                # API route handlers
│   ├── auth.py             # Authentication endpoints
│   ├── users.py            # User management
│   ├── habits.py           # Habit CRUD operations
│   └── trackers.py         # Habit tracking
└── schemas/                # SQLAlchemy schemas
    └── db_models.py

alembic/
├── versions/               # Database migrations
├── env.py                  # Alembic environment configuration
└── script.py.mako          # Migration template
```

## API Endpoints

### Authentication

- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get JWT token

### Users

- `GET /users/{user_id}` - Get user by ID (admin)
- `PUT /users/{user_id}` - Update user
- `DELETE /users/{user_id}` - Delete user

### Habits

- `GET /habits/` - List all habits
- `GET /habits/{habit_id}` - Get habit details
- `POST /habits/` - Create new habit
- `PUT /habits/{habit_id}` - Update habit
- `DELETE /habits/{habit_id}` - Delete habit

### Trackers

- `GET /trackers/` - List tracker entries
- `POST /trackers/` - Create tracker entry
- `PUT /trackers/{tracker_id}` - Update tracker entry
- `DELETE /trackers/{tracker_id}` - Delete tracker entry

## Configuration

Key configuration options in `src/habit_tracker/core/config.py`:

- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT signing key
- `ALGORITHM`: JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token expiration time
- `CORS_ORIGINS`: Allowed CORS origins

## Related Projects

- [Habit Tracker Front-End](https://github.com/kugelblitz104/habit-tracker-front-end) - React-based web interface

## License

This project is private and not licensed for public use.
