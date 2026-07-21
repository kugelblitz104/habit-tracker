"""add integration_connection.base_url (on-prem Azure DevOps host)

Revision ID: a3d1e5f7c9b2
Revises: f4b8d0c2a6e9
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3d1e5f7c9b2"
down_revision: Union[str, Sequence[str], None] = "f4b8d0c2a6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable host root for Azure DevOps connections; NULL means the public
    # cloud (https://dev.azure.com). Set it for on-prem Azure DevOps Server /
    # TFS, e.g. "https://tfs.example.com".
    op.add_column(
        "integration_connection",
        sa.Column("base_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_connection", "base_url")
