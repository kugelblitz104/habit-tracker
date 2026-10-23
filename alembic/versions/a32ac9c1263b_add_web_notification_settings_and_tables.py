"""add web notification settings and tables

Revision ID: a32ac9c1263b
Revises: 75894aeded77
Create Date: 2026-10-15 11:11:14.151775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a32ac9c1263b'
down_revision: Union[str, Sequence[str], None] = '75894aeded77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('push_subscription',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False),
    sa.Column('p256dh', sa.String(), nullable=False),
    sa.Column('auth', sa.String(), nullable=False),
    sa.Column('created_date', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['profile.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile_id', 'endpoint', name='uq_push_subscription_profile_endpoint')
    )
    op.create_index(op.f('ix_push_subscription_profile_id'), 'push_subscription', ['profile_id'], unique=False)
    op.create_table('scheduled_notification',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('entity_type', sa.String(), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('fire_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['profile.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity_type', 'entity_id', name='uq_scheduled_notification_entity')
    )
    op.create_index(op.f('ix_scheduled_notification_fire_at'), 'scheduled_notification', ['fire_at'], unique=False)
    op.create_index(op.f('ix_scheduled_notification_profile_id'), 'scheduled_notification', ['profile_id'], unique=False)
    op.add_column('profile', sa.Column('notify_task_due', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('profile', sa.Column('notify_task_scheduled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('profile', sa.Column('notify_habits', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('profile', sa.Column('notify_countdowns', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('profile', sa.Column('notify_journal', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('profile', sa.Column('task_due_reminder_offsets', sa.ARRAY(sa.Integer()), server_default='{60,15}', nullable=False))
    op.add_column('profile', sa.Column('task_scheduled_reminder_offsets', sa.ARRAY(sa.Integer()), server_default='{}', nullable=False))
    op.add_column('profile', sa.Column('task_reminder_default_time', sa.Time(), server_default='09:00:00', nullable=False))
    op.add_column('profile', sa.Column('timezone', sa.String(), nullable=True))
    op.add_column('task', sa.Column('due_reminder_offsets', sa.ARRAY(sa.Integer()), nullable=True))
    op.add_column('task', sa.Column('scheduled_reminder_offsets', sa.ARRAY(sa.Integer()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('task', 'scheduled_reminder_offsets')
    op.drop_column('task', 'due_reminder_offsets')
    op.drop_column('profile', 'timezone')
    op.drop_column('profile', 'task_reminder_default_time')
    op.drop_column('profile', 'task_scheduled_reminder_offsets')
    op.drop_column('profile', 'task_due_reminder_offsets')
    op.drop_column('profile', 'notify_journal')
    op.drop_column('profile', 'notify_countdowns')
    op.drop_column('profile', 'notify_habits')
    op.drop_column('profile', 'notify_task_scheduled')
    op.drop_column('profile', 'notify_task_due')
    op.drop_index(op.f('ix_scheduled_notification_profile_id'), table_name='scheduled_notification')
    op.drop_index(op.f('ix_scheduled_notification_fire_at'), table_name='scheduled_notification')
    op.drop_table('scheduled_notification')
    op.drop_index(op.f('ix_push_subscription_profile_id'), table_name='push_subscription')
    op.drop_table('push_subscription')
