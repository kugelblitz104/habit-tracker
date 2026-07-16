"""Tests for the Azure DevOps / GitHub integration endpoints.

External HTTP is never hit: the provider client is swapped for a FakeClient via
the get_client_builder dependency override (mirrors the calendar tests' fetcher
override).
"""

from sqlalchemy import select

from habit_tracker.main import app
from habit_tracker.schemas.db_models import IntegrationConnection, Task
from habit_tracker.services.integrations import ExternalItem, IntegrationError
from habit_tracker.services.integrations.azure_devops import html_to_text, text_to_html
from habit_tracker.services.integrations.base import get_client_builder
from tests.factories import (
    IntegrationConnectionFactory,
    ProfileFactory,
    TaskFactory,
    UserFactory,
)


async def login_as(client, user):
    login_response = await client.post(
        "/auth/login",
        data={"username": user.username, "password": "password123"},
    )
    token = login_response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})


class FakeClient:
    """Canned integration client (dependency-override target)."""

    def __init__(self, items=None, list_error=None, create_error=None):
        self.items = items or []
        self.list_error = list_error
        self.create_error = create_error
        self.created: list[tuple[str, str | None]] = []
        self.list_calls = 0

    async def list_open_assigned(self):
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return self.items

    async def create_item(self, title, body):
        if self.create_error is not None:
            raise self.create_error
        self.created.append((title, body))
        return ExternalItem(
            external_ref="AB#999",
            external_url="https://dev.azure.com/org/proj/_workitems/edit/999",
            title=title,
            description=body,
        )


def override_builder(fake):
    """Route every connection's client to `fake` for this test (cleared at
    client-fixture teardown)."""
    app.dependency_overrides[get_client_builder] = lambda: (lambda conn, token: fake)


class TestIntegrationConnectionCrud:
    async def test_create_github_connection(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/integrations/",
            json={
                "provider": "github",
                "name": "My GitHub",
                "profile_id": profile.id,
                "token": "ghp_secrettoken",
                "default_repo": "octocat/hello-world",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["provider"] == "github"
        assert data["has_token"] is True
        # The PAT must never be echoed back.
        assert "token" not in data
        assert "encrypted_token" not in data
        assert "ghp_secrettoken" not in response.text

    async def test_create_azure_requires_org_and_project(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/integrations/",
            json={
                "provider": "azure_devops",
                "name": "ADO",
                "profile_id": profile.id,
                "token": "pat",
            },
        )
        assert response.status_code == 422

    async def test_create_azure_connection(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/integrations/",
            json={
                "provider": "azure_devops",
                "name": "ADO",
                "profile_id": profile.id,
                "token": "pat",
                "organization": "contoso",
                "project": "Payments",
            },
        )
        assert response.status_code == 201
        assert response.json()["organization"] == "contoso"

    async def test_invalid_provider_rejected(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        await db_session.commit()
        await login_as(client, user)

        response = await client.post(
            "/integrations/",
            json={
                "provider": "gitlab",
                "name": "x",
                "profile_id": profile.id,
                "token": "pat",
            },
        )
        assert response.status_code == 422

    async def test_list_omits_token(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        IntegrationConnectionFactory(profile=profile, name="GH")
        await db_session.commit()
        await login_as(client, user)

        response = await client.get("/integrations/", params={"profile_id": profile.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["integration_connections"][0]["has_token"] is True
        assert "encrypted_token" not in response.text

    async def test_list_foreign_profile_forbidden(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        other = UserFactory()
        foreign = ProfileFactory(user=other, name="Theirs")
        await db_session.commit()
        await login_as(client, user)

        response = await client.get("/integrations/", params={"profile_id": foreign.id})
        assert response.status_code == 403

    async def test_patch_rotates_token_and_updates_name(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(profile=profile, name="Old")
        await db_session.commit()
        await login_as(client, user)

        response = await client.patch(
            f"/integrations/{conn.id}",
            json={"name": "New", "token": "ghp_rotated"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New"
        assert response.json()["has_token"] is True

    async def test_delete_connection(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(profile=profile)
        await db_session.commit()
        await login_as(client, user)

        response = await client.delete(f"/integrations/{conn.id}")
        assert response.status_code == 200

        gone = await db_session.execute(
            select(IntegrationConnection).filter(IntegrationConnection.id == conn.id)
        )
        assert gone.scalar_one_or_none() is None


class TestIntegrationSync:
    async def test_sync_imports_tasks(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(profile=profile, provider="github")
        await db_session.commit()
        await login_as(client, user)

        fake = FakeClient(
            items=[
                ExternalItem(
                    external_ref="octocat/hello#1",
                    external_url="https://github.com/octocat/hello/issues/1",
                    title="Fix bug",
                    description="Something broke",
                ),
                ExternalItem(
                    external_ref="octocat/hello#2",
                    external_url="https://github.com/octocat/hello/issues/2",
                    title="Add feature",
                    description=None,
                ),
            ]
        )
        override_builder(fake)

        response = await client.post(f"/integrations/{conn.id}/sync")
        assert response.status_code == 200
        body = response.json()
        assert body["tasks_imported"] == 2
        assert body["tasks_skipped"] == 0
        assert fake.list_calls == 1

        result = await db_session.execute(
            select(Task).filter(Task.profile_id == profile.id, Task.source == "github")
        )
        tasks = {t.external_ref: t for t in result.scalars().all()}
        assert set(tasks) == {"octocat/hello#1", "octocat/hello#2"}
        assert tasks["octocat/hello#1"].title == "Fix bug"
        assert tasks["octocat/hello#1"].notes == "Something broke"
        assert tasks["octocat/hello#1"].status == 0  # OPEN
        assert (
            tasks["octocat/hello#1"].external_url
            == "https://github.com/octocat/hello/issues/1"
        )

    async def test_sync_is_idempotent(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(profile=profile, provider="github")
        await db_session.commit()
        await login_as(client, user)

        items = [
            ExternalItem(
                external_ref="octocat/hello#1",
                external_url="https://github.com/octocat/hello/issues/1",
                title="Fix bug",
                description="x",
            )
        ]
        override_builder(FakeClient(items=items))

        first = await client.post(f"/integrations/{conn.id}/sync")
        assert first.json()["tasks_imported"] == 1

        second = await client.post(f"/integrations/{conn.id}/sync")
        assert second.json()["tasks_imported"] == 0
        assert second.json()["tasks_skipped"] == 1

        count = await db_session.execute(
            select(Task).filter(Task.profile_id == profile.id, Task.source == "github")
        )
        assert len(count.scalars().all()) == 1

    async def test_sync_provider_error_502(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(profile=profile, provider="github")
        await db_session.commit()
        await login_as(client, user)

        override_builder(
            FakeClient(list_error=IntegrationError("GitHub returned 401 Unauthorized"))
        )

        response = await client.post(f"/integrations/{conn.id}/sync")
        assert response.status_code == 502
        assert "401" in response.json()["detail"]

        refreshed = await db_session.get(IntegrationConnection, conn.id)
        await db_session.refresh(refreshed)
        assert refreshed.last_error is not None

    async def test_sync_foreign_connection_forbidden(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        other = UserFactory()
        foreign_profile = ProfileFactory(user=other, name="Theirs")
        conn = IntegrationConnectionFactory(profile=foreign_profile)
        await db_session.commit()
        await login_as(client, user)

        override_builder(FakeClient(items=[]))
        response = await client.post(f"/integrations/{conn.id}/sync")
        assert response.status_code == 403


class TestIntegrationPublish:
    async def test_publish_creates_and_links(self, client, db_session, setup_factories):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(
            profile=profile,
            provider="azure_devops",
            organization="contoso",
            project="Payments",
        )
        task = TaskFactory(profile=profile, title="Ship it", notes="the details")
        await db_session.commit()
        await login_as(client, user)

        fake = FakeClient()
        override_builder(fake)

        response = await client.post(
            f"/integrations/{conn.id}/publish", json={"task_id": task.id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "azure_devops"
        assert body["external_ref"] == "AB#999"
        assert fake.created == [("Ship it", "the details")]

        await db_session.refresh(task)
        assert task.source == "azure_devops"
        assert task.external_ref == "AB#999"
        assert task.external_url.endswith("/999")

    async def test_publish_rejects_already_linked(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        conn = IntegrationConnectionFactory(
            profile=profile, provider="azure_devops", organization="c", project="p"
        )
        task = TaskFactory(
            profile=profile,
            external_url="https://dev.azure.com/c/p/_workitems/edit/5",
        )
        await db_session.commit()
        await login_as(client, user)

        override_builder(FakeClient())
        response = await client.post(
            f"/integrations/{conn.id}/publish", json={"task_id": task.id}
        )
        assert response.status_code == 400
        assert "already linked" in response.json()["detail"].lower()

    async def test_publish_task_from_other_profile_400(
        self, client, db_session, setup_factories
    ):
        user = UserFactory()
        profile = ProfileFactory(user=user, name="Main")
        other_profile = ProfileFactory(user=user, name="Other")
        conn = IntegrationConnectionFactory(
            profile=profile, provider="azure_devops", organization="c", project="p"
        )
        task = TaskFactory(profile=other_profile, title="Elsewhere")
        await db_session.commit()
        await login_as(client, user)

        override_builder(FakeClient())
        response = await client.post(
            f"/integrations/{conn.id}/publish", json={"task_id": task.id}
        )
        assert response.status_code == 400


class TestAzureHtmlSerialization:
    """Azure DevOps System.Description is an HTML field: we import it as plain
    text and publish plain text back as minimal HTML."""

    def test_html_to_text_decodes_nbsp_and_block_tags(self):
        raw = "<div>Hello&nbsp;world</div><div>line&nbsp;two</div>"
        assert html_to_text(raw) == "Hello world\nline two"

    def test_html_to_text_br_and_entities(self):
        assert html_to_text("a&amp;b<br>c") == "a&b\nc"

    def test_html_to_text_list_items(self):
        assert html_to_text("<ul><li>one</li><li>two</li></ul>") == "- one\n- two"

    def test_html_to_text_none_and_empty(self):
        assert html_to_text(None) is None
        assert html_to_text("") == ""

    def test_text_to_html_escapes_and_preserves_newlines(self):
        assert text_to_html("a & b\nc<d") == "a &amp; b<br>\nc&lt;d"

    def test_text_to_html_empty(self):
        assert text_to_html(None) == ""
        assert text_to_html("") == ""
