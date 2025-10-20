FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

WORKDIR /code

COPY ./pyproject.toml /code/pyproject.toml

RUN uv sync
COPY ./src /code/src

WORKDIR /code/src

RUN alembic upgrade head
CMD ["uv", "run", "uvicorn", "habit_tracker.main:app", "--host", "0.0.0.0", "--port", "8080"]