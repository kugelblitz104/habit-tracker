"""API documentation tests.

This file pins the OpenAPI schema. The front-end generates its client from
/openapi.json, so any change to the schema, including property or parameter
order, breaks it. A deliberate schema change means regenerating the snapshot
and reviewing its diff:

    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_api_docs.py
"""

import difflib
import json
import os
from pathlib import Path

from habit_tracker.main import app

SNAPSHOT = Path(__file__).parent / "openapi.snapshot.json"
MAX_DIFF_LINES = 80


def _dump(schema: dict) -> str:
    """Serialise without key sorting, so order differences show up."""
    return json.dumps(schema, indent=2, ensure_ascii=False)


class TestOpenAPISchema:
    """The live schema matches the committed snapshot exactly, order included."""

    def test_schema_matches_snapshot(self):
        live = _dump(app.openapi())
        if os.environ.get("UPDATE_OPENAPI_SNAPSHOT"):
            SNAPSHOT.write_text(live + "\n", encoding="utf-8", newline="\n")
            return
        expected = _dump(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
        if live == expected:
            return
        diff = list(
            difflib.unified_diff(
                expected.splitlines(),
                live.splitlines(),
                "snapshot",
                "live",
                lineterm="",
            )
        )
        shown = "\n".join(diff[:MAX_DIFF_LINES])
        omitted = len(diff) - MAX_DIFF_LINES
        if omitted > 0:
            shown += f"\n... {omitted} more diff lines"
        raise AssertionError(
            "OpenAPI schema differs from tests/openapi.snapshot.json.\n"
            "If the change is deliberate, regenerate with:\n"
            "    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_api_docs.py\n\n"
            + shown
        )


class TestSwaggerUI:
    """Tests for Swagger UI."""

    async def test_swagger_ui_available(self, shared_client):
        """Swagger UI is accessible."""
        response = await shared_client.get("/docs")
        # May return 200 or redirect
        assert response.status_code in [200, 307]

    async def test_swagger_ui_html_content(self, shared_client):
        """Swagger UI returns HTML."""
        response = await shared_client.get("/docs", follow_redirects=True)
        if response.status_code == 200:
            assert "text/html" in response.headers.get("content-type", "")


class TestReDoc:
    """Tests for ReDoc documentation."""

    async def test_redoc_available(self, shared_client):
        """ReDoc is accessible."""
        response = await shared_client.get("/redoc")
        # May return 200 or redirect
        assert response.status_code in [200, 307]

    async def test_redoc_html_content(self, shared_client):
        """ReDoc returns HTML."""
        response = await shared_client.get("/redoc", follow_redirects=True)
        if response.status_code == 200:
            assert "text/html" in response.headers.get("content-type", "")
