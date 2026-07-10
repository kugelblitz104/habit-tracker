# NOTE: this image expects `zscaler-ca.pem` (corporate TLS-interception CA
# bundle) to be present in the build context. It is NOT committed to the repo
# (gitignored — never commit certificates). Use ./build.sh, which stages the
# bundle from outside the repo transiently and removes it after the build.
FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

# Install the corporate CA bundle into the system trust store BEFORE any step
# that talks to the network (uv sync), so TLS verification works behind the
# Zscaler proxy at both build time and runtime.
COPY ./zscaler-ca.pem /usr/local/share/ca-certificates/zscaler-ca.crt
RUN update-ca-certificates

# Point Python/httpx (httpx >= 0.28 honors SSL_CERT_FILE) and pip at the
# combined system bundle; UV_NATIVE_TLS makes uv use the system trust store.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV UV_NATIVE_TLS=true

WORKDIR /code

COPY ./pyproject.toml /code/pyproject.toml

RUN uv sync
COPY ./src /code/src

COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

CMD uv run alembic upgrade head && uv run uvicorn src.habit_tracker.main:app --host 0.0.0.0 --port 8080
