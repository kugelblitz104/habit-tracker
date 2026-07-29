"""Shared types + client factory for the external integrations."""

from dataclasses import dataclass
from typing import Callable, List, Protocol, runtime_checkable

import httpx

from habit_tracker.constants import IntegrationProvider
from habit_tracker.schemas.db_models import IntegrationConnection


class IntegrationError(Exception):
    """Raised when an external provider call fails (auth, HTTP, or network).

    The router turns this into a 502 with the message, so keep messages
    user-facing ("Azure DevOps returned 401 Unauthorized — check the PAT").
    """


def transport_error_message(
    exc: httpx.HTTPError, provider: str, host: str | None = None
) -> str:
    """Turn a low-level httpx transport failure into a user-facing message.

    A connect/DNS failure — the backend can't even reach the host — is the most
    common on-prem misconfiguration, and httpx surfaces it as an opaque
    ``[Errno -2] Name or service not known``. Name the host and point at the
    real cause: the *server* running this app (not the user's browser) has to
    reach the host, so an internal/on-prem endpoint needs network or VPN access
    from wherever the backend is deployed.
    """
    where = f" at {host}" if host else ""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return (
            f"Couldn't reach {provider}{where}. Check the server URL, and note "
            f"that the host must be reachable from the server running this app "
            f"— an on-prem endpoint needs network/VPN access from the backend, "
            f"not just from your browser."
        )
    if isinstance(exc, httpx.TimeoutException):
        return f"{provider} timed out{where}. The host may be slow or unreachable."
    return f"{provider} request failed: {exc}"


def raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.is_success:
        return
    detail = resp.text[:300] if resp.text else ""
    raise IntegrationError(
        f"{provider} returned {resp.status_code} {resp.reason_phrase}. {detail}".strip()
    )


@dataclass
class ExternalItem:
    """A work item / issue, normalized across providers."""

    external_ref: str  # e.g. "AB#2841" or "owner/repo#42"
    external_url: str
    title: str
    description: str | None = None


@runtime_checkable
class IntegrationClient(Protocol):
    async def list_open_assigned(self) -> List[ExternalItem]:
        """The current user's open items assigned to them."""
        ...

    async def create_item(self, title: str, body: str | None) -> ExternalItem:
        """Create a new work item / issue and return its link."""
        ...


# A builder turns a stored connection + its decrypted PAT into a live client.
ClientBuilder = Callable[[IntegrationConnection, str], IntegrationClient]


def build_client(connection: IntegrationConnection, token: str) -> IntegrationClient:
    """Construct the provider client for a connection. `token` is the decrypted
    PAT (the caller decrypts; clients never touch the ciphertext)."""
    # Imported lazily to avoid a circular import at module load.
    from habit_tracker.services.integrations.azure_devops import AzureDevOpsClient
    from habit_tracker.services.integrations.github import GitHubClient

    if connection.provider == IntegrationProvider.AZURE_DEVOPS.value:
        return AzureDevOpsClient(
            organization=connection.organization or "",
            project=connection.project or "",
            token=token,
            work_item_type=connection.work_item_type or "Task",
            base_url=connection.base_url,
        )
    if connection.provider == IntegrationProvider.GITHUB.value:
        return GitHubClient(token=token, default_repo=connection.default_repo)
    raise IntegrationError(f"Unknown integration provider: {connection.provider!r}")


def get_client_builder() -> ClientBuilder:
    """FastAPI dependency returning the real builder; overridden in tests."""
    return build_client
