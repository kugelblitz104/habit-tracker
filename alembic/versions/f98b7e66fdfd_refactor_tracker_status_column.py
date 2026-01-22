"""refactor_tracker_status_column

Revision ID: f98b7e66fdfd
Revises: 4a30fe0d63b9
Create Date: 2026-01-22 13:40:39.638694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f98b7e66fdfd'
down_revision: Union[str, Sequence[str], None] = '4a30fe0d63b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add status column with default value 2 (completed)
    # 0 = not completed, 1 = skipped, 2 = completed
    op.add_column('tracker', sa.Column('status', sa.Integer(), nullable=False, server_default='2'))
    
    # Migrate existing data:
    # - If skipped=True, set status=1
    # - If completed=True, set status=2
    # - Otherwise, set status=0
    op.execute("""
        UPDATE tracker 
        SET status = CASE 
            WHEN skipped = TRUE THEN 1
            WHEN completed = TRUE THEN 2
            ELSE 0
        END
    """)
    
    # Drop the old columns
    op.drop_column('tracker', 'completed')
    op.drop_column('tracker', 'skipped')


def downgrade() -> None:
    """Downgrade schema."""
    # Re-add the old columns
    op.add_column('tracker', sa.Column('completed', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('tracker', sa.Column('skipped', sa.Boolean(), nullable=False, server_default='false'))
    
    # Migrate data back from status to completed/skipped
    op.execute("""
        UPDATE tracker 
        SET completed = CASE WHEN status = 2 THEN TRUE ELSE FALSE END,
            skipped = CASE WHEN status = 1 THEN TRUE ELSE FALSE END
    """)
    
    # Drop the status column
    op.drop_column('tracker', 'status')
