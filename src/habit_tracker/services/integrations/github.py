"""GitHub issues client (PAT auth)."""

import logging
from typing import List, Optional

import httpx

from habit_tracker.services.integrations.base import ExternalItem, IntegrationError

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
TIMEOUT_SECONDS = 15.0
_MAX_ITEMS = 200


class GitHubClient:
    def __init__(self, token: str, default_repo: Optional[str] = None):
        self.token = token
        self.default_repo = default_repo

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "habit-tracker-integration",
        }

    async def list_open_assigned(self) -> List[ExternalItem]:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, headers=self._headers()
            ) as http:
                # The cross-repo /issues endpoint returns issues assigned to the
                # authenticated user, each carrying its `repository` object.
                resp = await http.get(
                    f"{API_BASE}/issues",
                    params={"filter": "assigned", "state": "open", "per_page": 100},
                )
                _raise_for_status(resp, "GitHub")
        except httpx.HTTPError as exc:
            raise IntegrationError(f"GitHub request failed: {exc}") from exc

        items: List[ExternalItem] = []
        for issue in resp.json()[:_MAX_ITEMS]:
            # The /issues feed includes pull requests; exclude them.
            if "pull_request" in issue:
                continue
            repo = (issue.get("repository") or {}).get("full_name")
            number = issue.get("number")
            if not repo or number is None:
                continue
            items.append(
                ExternalItem(
                    external_ref=f"{repo}#{number}",
                    external_url=issue.get("html_url", ""),
                    title=issue.get("title") or f"Issue {number}",
                    description=issue.get("body"),
                )
            )
        return items

    async def create_item(self, title: str, body: str | None) -> ExternalItem:
        if not self.default_repo:
            raise IntegrationError(
                "This GitHub connection has no target repository set. Add a "
                'default repo ("owner/repo") before publishing.'
            )
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, headers=self._headers()
            ) as http:
                resp = await http.post(
                    f"{API_BASE}/repos/{self.default_repo}/issues",
                    json={"title": title, "body": body or ""},
                )
                _raise_for_status(resp, "GitHub")
        except httpx.HTTPError as exc:
            raise IntegrationError(f"GitHub request failed: {exc}") from exc

        data = resp.json()
        number = data["number"]
        return ExternalItem(
            external_ref=f"{self.default_repo}#{number}",
            external_url=data.get("html_url", ""),
            title=title,
            description=body,
        )


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.is_success:
        return
    detail = resp.text[:300] if resp.text else ""
    raise IntegrationError(
        f"{provider} returned {resp.status_code} {resp.reason_phrase}. {detail}".strip()
    )
