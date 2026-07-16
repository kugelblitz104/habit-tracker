from datetime import datetime
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from habit_tracker.constants import IntegrationProvider

_PROVIDER_VALUES = {p.value for p in IntegrationProvider}


class IntegrationConnectionBase(BaseModel):
    provider: str
    name: str
    # Azure DevOps
    organization: Optional[str] = None
    project: Optional[str] = None
    work_item_type: Optional[str] = None
    # GitHub
    default_repo: Optional[str] = None
    enabled: bool = True

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in _PROVIDER_VALUES:
            raise ValueError(
                f"provider must be one of {sorted(_PROVIDER_VALUES)}"
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v

    @field_validator("default_repo")
    @classmethod
    def validate_default_repo(cls, v: Optional[str]) -> Optional[str]:
        # Empty string -> treat as unset; otherwise must look like "owner/repo".
        if v is None or not v.strip():
            return None
        v = v.strip()
        parts = v.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError('default_repo must be in the form "owner/repo"')
        return v

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
        if not v.strip():
            raise ValueError("token (PAT) cannot be empty")
        return v.strip()


class IntegrationConnectionRead(IntegrationConnectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    has_token: bool = False
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_date: datetime
    updated_date: Optional[datetime] = None


class IntegrationConnectionUpdate(BaseModel):
    name: Optional[str] = None
    organization: Optional[str] = None
    project: Optional[str] = None
    work_item_type: Optional[str] = None
    default_repo: Optional[str] = None
    enabled: Optional[bool] = None
    # Provide to rotate the PAT; omit to leave it unchanged.
    token: Optional[str] = None

    @field_validator("name", "enabled")
    @classmethod
    def reject_null(cls, v: object, info: ValidationInfo) -> object:
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("token (PAT) cannot be empty")
        return v.strip() if v is not None else v

    @field_validator("default_repo")
    @classmethod
    def validate_default_repo(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return v
        v = v.strip()
        parts = v.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError('default_repo must be in the form "owner/repo"')
        return v


class IntegrationConnectionList(BaseModel):
    integration_connections: List[IntegrationConnectionRead] = []
    total: int
    limit: int
    offset: int


class IntegrationSyncResult(BaseModel):
    """Summary of a manual "Sync now" pull of assigned open items into tasks."""

    success: bool
    message: str
    tasks_imported: int = 0
    tasks_skipped: int = 0
    details: List[str] = []  # external refs of imported items
    errors: List[str] = []


class PublishRequest(BaseModel):
    task_id: int


class PublishResult(BaseModel):
    source: str
    external_ref: str
    external_url: str
