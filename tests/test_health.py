"""Tests for GET /health, the container and Railway readiness probe."""

from sqlalchemy.exc import OperationalError

from habit_tracker.core.dependencies import get_db
from habit_tracker.main import app


class TestHealth:
    async def test_ok_when_the_database_answers(self, client):
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_503_when_the_database_is_unreachable(self, client):
        class DeadSession:
            async def execute(self, *_args, **_kwargs):
                raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        async def dead_db():
            yield DeadSession()

        app.dependency_overrides[get_db] = dead_db

        response = await client.get("/health")

        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}

    async def test_needs_no_auth(self, client):
        """No login_as: a probe carries no token."""
        response = await client.get("/health")

        assert response.status_code == 200

    def test_is_absent_from_the_openapi_schema(self):
        """The front-end generates its client from /openapi.json; a probe
        route there would add a client method nothing calls."""
        assert "/health" not in app.openapi()["paths"]
