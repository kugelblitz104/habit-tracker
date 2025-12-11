"""API documentation tests."""


class TestOpenAPISchema:
    """Tests for OpenAPI schema."""

    async def test_openapi_json_available(self, shared_client):
        """OpenAPI JSON schema is accessible."""
        response = await shared_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
        assert "components" in data

    async def test_openapi_version(self, shared_client):
        """OpenAPI version is specified."""
        response = await shared_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["openapi"].startswith("3.")

    async def test_openapi_info_section(self, shared_client):
        """OpenAPI info section is present."""
        response = await shared_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "info" in data
        assert "title" in data["info"]

    async def test_openapi_paths_defined(self, shared_client):
        """API paths are defined in schema."""
        response = await shared_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        paths = data["paths"]
        # Check key endpoints are documented
        assert (
            "/auth/login" in paths
            or "/login" in paths
            or any("login" in path for path in paths)
        )
        assert "/users/" in paths or "/users" in paths
        assert "/habits/" in paths or "/habits" in paths
        assert "/trackers/" in paths or "/trackers" in paths

    async def test_openapi_schemas_defined(self, shared_client):
        """Response schemas are defined."""
        response = await shared_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        schemas = data.get("components", {}).get("schemas", {})
        assert len(schemas) > 0


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
