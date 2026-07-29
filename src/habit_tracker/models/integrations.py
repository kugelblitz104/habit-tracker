from datetime import datetime

from pydantic import (
    BaseModel,
    ValidationInfo,
    field_validator,
    model_validator,
)

from habit_tracker.constants import IntegrationProvider
from habit_tracker.models._base import _FromORM
from habit_tracker.models._validators import (
    non_blank_string,
    non_empty_token,
    normalize_base_url,
    reject_null,
    validate_membership,
    validate_owner_repo,
)

_PROVIDER_VALUES = {p.value for p in IntegrationProvider}


def _validate_provider(v: str) -> str:
    return validate_membership(
        v, _PROVIDER_VALUES, f"provider must be one of {sorted(_PROVIDER_VALUES)}"
    )


class IntegrationConnectionBase(BaseModel):
    provider: str
    name: str
    # Azure DevOps
    organization: str | None = None
    project: str | None = None
    work_item_type: str | None = None
    # Optional host root for on-prem Azure DevOps Server / TFS (e.g.
    # "https://tfs.example.com"); leave unset for the public cloud.
    base_url: str | None = None
    # GitHub
    default_repo: str | None = None
    enabled: bool = True

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        return _validate_provider(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return non_blank_string(v, "Name")

    @field_validator("default_repo")
    @classmethod
    def validate_default_repo(cls, v: str | None) -> str | None:
        # Empty string -> treat as unset; otherwise must look like "owner/repo".
        if v is None or not v.strip():
            return None
        return validate_owner_repo(v.strip())

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        return normalize_base_url(v)

    @model_validator(mode="after")
    def validate_provider_fields(self) -> "IntegrationConnectionBase":
        # Azure DevOps needs an org + project to address work items; GitHub reads
        # assigned issues without a repo (publishing needs default_repo, which is
        # enforced at publish time so a read-only connection can omit it).
        if self.provider == IntegrationProvider.AZURE_DEVOPS.value:
            if not (self.organization and self.organization.strip()):
                raise ValueError("organization is required for Azure DevOps")
            if not (self.project and self.project.strip()):
                raise ValueError("project is required for Azure DevOps")
        return self


class IntegrationConnectionCreate(IntegrationConnectionBase):
    profile_id: int
    # Plaintext PAT; stored encrypted, never echoed back.
    token: str

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        return non_empty_token(v)


class IntegrationConnectionRead(IntegrationConnectionBase, _FromORM):
    id: int
    profile_id: int
    has_token: bool = False
    last_synced_at: datetime | None = None
    last_error: str | None = None
    created_date: datetime
    updated_date: datetime | None = None


class IntegrationConnectionUpdate(BaseModel):
    name: str | None = None
    organization: str | None = None
    project: str | None = None
    work_item_type: str | None = None
    base_url: str | None = None
    default_repo: str | None = None
    enabled: bool | None = None
    # Provide to rotate the PAT; omit to leave it unchanged.
    token: str | None = None

    @field_validator("name", "enabled")
    @classmethod
    def validate_reject_null(cls, v: object, info: ValidationInfo) -> object:
        return reject_null(v, info)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return non_blank_string(v, "Name")

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str | None) -> str | None:
        return non_empty_token(v)

    @field_validator("default_repo")
    @classmethod
    def validate_default_repo(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return v
        return validate_owner_repo(v.strip())

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        return normalize_base_url(v)


class IntegrationConnectionList(BaseModel):
    integration_connections: list[IntegrationConnectionRead] = []
    total: int
    limit: int
    offset: int


class IntegrationSyncResult(BaseModel):
    """Summary of a manual "Sync now" pull of assigned open items into tasks."""

    success: bool
    message: str
    tasks_imported: int = 0
    tasks_skipped: int = 0
    details: list[str] = []  # external refs of imported items
    errors: list[str] = []


class PublishRequest(BaseModel):
    task_id: int


class PublishResult(BaseModel):
    source: str
    external_ref: str
    external_url: str
