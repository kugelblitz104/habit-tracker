# LOCAL DEV ONLY: building behind the corporate (Zscaler) TLS proxy requires
# its CA bundle. `./build.sh` stages `zscaler-ca.pem` (gitignored — never
# commit certificates) into the build context transiently; the conditional
# install below only runs when that file is present. Deployment/CI builds
# without the file produce a clean image with no corporate CA in it.
FROM python:3.11-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root

# Point Python/httpx (httpx >= 0.28 honors SSL_CERT_FILE) and pip at the
# system bundle; UV_NATIVE_TLS makes uv use the system trust store. Both are
# no-ops on a clean deployment image (the bundle only gains the corporate CA
# when the local-dev conditional below installs it).
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV UV_NATIVE_TLS=true

WORKDIR /code

# The `zscaler-ca.pem*` glob matches nothing in deployment builds; a COPY with
# at least one matching source silently skips non-matching globs, so this line
# works with or without the staged cert.
COPY ./pyproject.toml ./zscaler-ca.pem* /code/

# LOCAL DEV ONLY: install the corporate CA into the system trust store BEFORE
# any step that talks to the network (uv sync), so TLS verification works
# behind the Zscaler proxy at both build time and runtime.
RUN if [ -f /code/zscaler-ca.pem ]; then \
        cp /code/zscaler-ca.pem /usr/local/share/ca-certificates/zscaler-ca.crt && \
        update-ca-certificates && \
        rm /code/zscaler-ca.pem; \
    else \
        echo "No corporate CA staged - building a clean (deployment) image"; \
    fi

RUN uv sync
COPY ./src /code/src

COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

CMD uv run alembic upgrade head && uv run uvicorn src.habit_tracker.main:app --host 0.0.0.0 --port 8080
