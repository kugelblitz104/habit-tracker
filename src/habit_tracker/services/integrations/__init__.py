"""External task-tracker integrations (Azure DevOps, GitHub).

Each provider client implements `IntegrationClient`: pull the current user's
open assigned items, and create a new item from a task. Clients are built via
`build_client`, exposed behind the `get_client_builder` FastAPI dependency so
tests can inject fakes without real network calls (mirrors the calendar
service's `get_ics_fetcher` pattern).
"""

from habit_tracker.services.integrations.base import (
    ClientBuilder,
    ExternalItem,
    IntegrationClient,
    IntegrationError,
    build_client,
    get_client_builder,
)

__all__ = [
    "ClientBuilder",
    "ExternalItem",
    "IntegrationClient",
    "IntegrationError",
    "build_client",
    "get_client_builder",
]
