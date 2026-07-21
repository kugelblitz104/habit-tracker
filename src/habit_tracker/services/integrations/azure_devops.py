"""Azure DevOps work-item client (PAT / Basic auth)."""

import html as html_lib
import logging
import re
from typing import List

import httpx

from habit_tracker.services.integrations.base import ExternalItem, IntegrationError

logger = logging.getLogger(__name__)


def html_to_text(value: str | None) -> str | None:
    """Flatten Azure DevOps rich-text HTML (System.Description is an HTML field)
    into readable plain text: <br> and block-close tags become newlines, list
    items become "- ", remaining tags are stripped, and HTML entities are
    decoded (so the stray "&nbsp;" et al. don't leak into task notes)."""
    if not value:
        return value
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6]|ul|ol)\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)  # strip any remaining tags
    text = html_lib.unescape(text)  # &nbsp; -> \xa0, &amp; -> &, ...
    text = text.replace("\xa0", " ")  # non-breaking space -> normal space
    text = re.sub(r"[ \t]+\n", "\n", text)  # trim trailing whitespace per line
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse long blank runs
    return text.strip()


def text_to_html(value: str | None) -> str:
    """Serialize plain-text task notes into minimal HTML for a work item's
    System.Description (an HTML field): escape special characters and preserve
    line breaks, so newlines/`&`/`<` survive instead of collapsing."""
    if not value:
        return ""
    return html_lib.escape(value).replace("\n", "<br>\n")

API_VERSION = "7.0"
TIMEOUT_SECONDS = 15.0

# Open = anything not in a terminal/closed meta-state. States vary by process
# template, so match the common closed-state names rather than an allowlist.
_CLOSED_STATES = "'Closed','Done','Removed','Resolved','Completed'"
_WIQL = (
    "SELECT [System.Id] FROM WorkItems "
    "WHERE [System.AssignedTo] = @Me "
    f"AND [System.State] NOT IN ({_CLOSED_STATES}) "
    "ORDER BY [System.ChangedDate] DESC"
)
_MAX_ITEMS = 200


class AzureDevOpsClient:
    def __init__(
        self,
        organization: str,
        project: str,
        token: str,
        work_item_type: str = "Task",
        base_url: str | None = None,
    ):
        self.organization = organization
        self.project = project
        self.token = token
        self.work_item_type = work_item_type
        # `base_url` is the host root; it defaults to the public cloud but points
        # at an on-prem Azure DevOps Server / TFS host when set (e.g.
        # "https://tfs.example.com"). It replaces only the "https://dev.azure.com"
        # prefix — the organization (cloud) / collection (on-prem) and project
        # segments are appended the same way for both, so the resulting URLs
        # match what you'd see in the browser: {host}/{org}/{project}/_apis/...
        host = (base_url or "https://dev.azure.com").rstrip("/")
        self.org_base = f"{host}/{organization}"
        self.project_base = f"{self.org_base}/{project}"

    def _work_item_url(self, work_item_id: int) -> str:
        return f"{self.org_base}/{self.project}/_workitems/edit/{work_item_id}"

    async def list_open_assigned(self) -> List[ExternalItem]:
        # PAT auth is HTTP Basic with an empty username.
        auth = ("", self.token)
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, auth=auth
            ) as http:
                wiql_resp = await http.post(
                    f"{self.project_base}/_apis/wit/wiql",
                    params={"api-version": API_VERSION},
                    json={"query": _WIQL},
                )
                _raise_for_status(wiql_resp, "Azure DevOps")
                work_items = (wiql_resp.json().get("workItems") or [])[:_MAX_ITEMS]
                ids = [str(w["id"]) for w in work_items]
                if not ids:
                    return []

                detail_resp = await http.get(
                    f"{self.project_base}/_apis/wit/workitems",
                    params={
                        "ids": ",".join(ids),
                        "fields": "System.Title,System.Description,System.State",
                        "api-version": API_VERSION,
                    },
                )
                _raise_for_status(detail_resp, "Azure DevOps")
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Azure DevOps request failed: {exc}") from exc

        items: List[ExternalItem] = []
        for wi in detail_resp.json().get("value", []):
            fields = wi.get("fields", {})
            wid = wi["id"]
            items.append(
                ExternalItem(
                    external_ref=f"AB#{wid}",
                    external_url=self._work_item_url(wid),
                    title=fields.get("System.Title") or f"Work item {wid}",
                    description=html_to_text(fields.get("System.Description")),
                )
            )
        return items

    async def create_item(self, title: str, body: str | None) -> ExternalItem:
        auth = ("", self.token)
        # Work-item creation uses the JSON Patch content type.
        patch = [{"op": "add", "path": "/fields/System.Title", "value": title}]
        if body:
            patch.append(
                {
                    "op": "add",
                    "path": "/fields/System.Description",
                    "value": text_to_html(body),
                }
            )
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, auth=auth
            ) as http:
                resp = await http.post(
                    f"{self.project_base}/_apis/wit/workitems/${self.work_item_type}",
                    params={"api-version": API_VERSION},
                    headers={"Content-Type": "application/json-patch+json"},
                    json=patch,
                )
                _raise_for_status(resp, "Azure DevOps")
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Azure DevOps request failed: {exc}") from exc

        data = resp.json()
        wid = data["id"]
        html = (data.get("_links", {}).get("html", {}) or {}).get("href")
        return ExternalItem(
            external_ref=f"AB#{wid}",
            external_url=html or self._work_item_url(wid),
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
