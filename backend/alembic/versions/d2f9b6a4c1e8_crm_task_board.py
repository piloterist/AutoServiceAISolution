"""crm task board (доска задач CRM)

Revision ID: d2f9b6a4c1e8
Revises: c4a8e1f7b923
Create Date: 2026-11-15 00:00:00.000000

The crm_tasks table (a phone taken under control from a call; its column on the board is
`status`) and the two thresholds, in days, after which a card in "На контроле" turns pink / red
(app_settings).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2f9b6a4c1e8'
down_revision: Union[str, None] = 'c4a8e1f7b923'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('crm_task_warn_days', sa.Integer(), server_default='1', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column('crm_task_overdue_days', sa.Integer(), server_default='3', nullable=False),
    )

    op.create_table(
        'crm_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('call_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('call_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('workshop_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('manual_moved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('inspection_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('client_name', sa.String(length=255), nullable=True),
        sa.Column('car_description', sa.String(length=500), nullable=True),
        sa.Column('request_number', sa.String(length=100), nullable=True),
        sa.Column('work_order_number', sa.String(length=100), nullable=True),
        sa.Column('refuse_reason', sa.Text(), nullable=True),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by_name', sa.String(length=255), nullable=False),
        sa.Column('moved_by_name', sa.String(length=255), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['call_id'], ['telephony_calls.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_crm_tasks_phone'), 'crm_tasks', ['phone'], unique=False)
    op.create_index(op.f('ix_crm_tasks_workshop_id'), 'crm_tasks', ['workshop_id'], unique=False)
    op.create_index(op.f('ix_crm_tasks_status'), 'crm_tasks', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_crm_tasks_status'), table_name='crm_tasks')
    op.drop_index(op.f('ix_crm_tasks_workshop_id'), table_name='crm_tasks')
    op.drop_index(op.f('ix_crm_tasks_phone'), table_name='crm_tasks')
    op.drop_table('crm_tasks')
    op.drop_column('app_settings', 'crm_task_overdue_days')
    op.drop_column('app_settings', 'crm_task_warn_days')
