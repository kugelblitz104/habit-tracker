# LOCAL DEV ONLY: building behind the corporate (Zscaler) TLS proxy requires its
# CA. It is supplied as a build secret (id=zscaler_ca) — never committed, never
# copied into the build context or an image layer. The conditional install below
# runs only when the secret is present; deployment/CI builds omit it entirely
# and produce a clean image with no corporate CA in it.
FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

# Point Python/httpx (httpx >= 0.28 honors SSL_CERT_FILE) and pip at the
# system bundle; UV_SYSTEM_CERTS makes uv use the system trust store (replaces
# the now-deprecated UV_NATIVE_TLS). Both are no-ops on a clean deployment image
# (the bundle only gains the corporate CA when the local-dev conditional below
# installs it).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV UV_SYSTEM_CERTS=true

WORKDIR /code

# uv.lock is copied alongside pyproject so `uv sync --frozen` installs the exact
# locked versions (reproducible builds) instead of re-resolving at build time.
COPY ./pyproject.toml ./uv.lock /code/

# LOCAL DEV ONLY: install the corporate CA from the build secret BEFORE any step
# that talks to the network (uv sync), so TLS verification works behind the
# Zscaler proxy. The secret is mounted only for this RUN — it never enters the
# build context or an image layer. When no secret is supplied (deployment/CI)
# the guard is a no-op and the image stays clean. The resulting trusted CA *is*
# baked in, which is intended: runtime httpx (Azure DevOps / GitHub) also
# traverses the proxy.
RUN --mount=type=secret,id=zscaler_ca \
    if [ -s /run/secrets/zscaler_ca ]; then \
        cp /run/secrets/zscaler_ca /usr/local/share/ca-certificates/zscaler-ca.crt && \
        update-ca-certificates; \
    else \
        echo "No corporate CA secret provided - building a clean (deployment) image"; \
    fi

RUN uv sync --frozen
COPY ./src /code/src

COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

CMD uv run alembic upgrade head && uv run uvicorn src.habit_tracker.main:app --host 0.0.0.0 --port 8080
