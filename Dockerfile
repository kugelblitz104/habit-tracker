# Image for local compose, deployment and CI. No build secrets, so it builds
# on any Docker builder (Railway's Metal builder only supports type=cache
# mounts, not type=secret).
FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

# Point Python/httpx (httpx >= 0.28 honors SSL_CERT_FILE) and pip at the system
# bundle; UV_SYSTEM_CERTS makes uv use the system trust store. On this clean
# image the bundle holds only the stock public CAs — which is all a deployment
# needs (no proxy in front of it).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV UV_SYSTEM_CERTS=true

# glibc otherwise creates up to 8 malloc arenas per host CPU (not per container
# limit), and the threadpool behind sync dependencies fragments across them.
ENV MALLOC_ARENA_MAX=2
ENV PATH="/code/.venv/bin:$PATH"

WORKDIR /code

# uv.lock is copied alongside pyproject so `uv sync --frozen` installs the exact
# locked versions (reproducible builds) instead of re-resolving at build time.
COPY ./pyproject.toml ./uv.lock /code/

# Dependencies first (cached layer), then the project itself once src/ exists:
# an editable install built before src/ is copied maps no packages.
RUN uv sync --frozen --no-dev --no-install-project
COPY ./src /code/src
RUN uv sync --frozen --no-dev

COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

# urlopen raises on a non-2xx, so a 503 from /health fails the check. Railway
# ignores HEALTHCHECK and probes railway.toml's healthcheckPath instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=4)"

# Venv binaries directly, not `uv run`, so no uv process stays resident; exec
# makes uvicorn PID 1 instead of a child of sh.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.habit_tracker.main:app --host 0.0.0.0 --port 8080"]
