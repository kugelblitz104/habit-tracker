# Production / CI image — clean, with no corporate CA and no build secrets, so
# it builds on any Docker builder (Railway's Metal builder only supports
# type=cache mounts, not type=secret). Local builds behind the corporate
# (Zscaler) TLS proxy use Dockerfile.zscaler instead (see docker-compose.yml),
# which layers the CA in via a build secret.
FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

# Point Python/httpx (httpx >= 0.28 honors SSL_CERT_FILE) and pip at the system
# bundle; UV_SYSTEM_CERTS makes uv use the system trust store. On this clean
# image the bundle holds only the stock public CAs — which is all a deployment
# needs (no proxy in front of it).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV UV_SYSTEM_CERTS=true

WORKDIR /code

# uv.lock is copied alongside pyproject so `uv sync --frozen` installs the exact
# locked versions (reproducible builds) instead of re-resolving at build time.
COPY ./pyproject.toml ./uv.lock /code/

RUN uv sync --frozen
COPY ./src /code/src

COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

CMD uv run alembic upgrade head && uv run uvicorn src.habit_tracker.main:app --host 0.0.0.0 --port 8080
