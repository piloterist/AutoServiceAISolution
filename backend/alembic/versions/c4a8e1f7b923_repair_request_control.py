"""repair request control (контроль заявок на ремонт)

Revision ID: c4a8e1f7b923
Revises: e1b7c4d9f058
Create Date: 2026-11-06 00:00:00.000000

Settings of the control (app_settings), the role right to disqualify a request without
attempts (role_tab_visibility), the disqualification fields on a request (work_orders) and
the table of manual attempts. The right is seeded true for Админ and Управляющий.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4a8e1f7b923'
down_revision: Union[str, None] = 'e1b7c4d9f058'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('request_control_enabled', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column('request_first_call_days', sa.Integer(), server_default='3', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column('request_second_call_days', sa.Integer(), server_default='7', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column('request_min_talk_sec', sa.Integer(), server_default='20', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column('request_popup_enabled', sa.Boolean(), server_default='true', nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'request_popup_interval_minutes', sa.Integer(), server_default='30', nullable=False
        ),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'request_auto_disqualify_days', sa.Integer(), server_default='30', nullable=False
        ),
    )

    op.add_column(
        'role_tab_visibility',
        sa.Column(
            'request_disqualify_unchecked', sa.Boolean(), server_default='false', nullable=False
        ),
    )
    op.execute(
        "UPDATE role_tab_visibility SET request_disqualify_unchecked = true "
        "WHERE role IN ('Админ', 'Управляющий')"
    )

    op.add_column(
        'work_orders',
        sa.Column('request_disqualified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'work_orders', sa.Column('request_disqualified_by', sa.String(length=255), nullable=True)
    )
    op.add_column(
        'work_orders',
        sa.Column('request_disqualify_reason', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'work_orders', sa.Column('request_disqualify_comment', sa.Text(), nullable=True)
    )

    op.create_table(
        'repair_request_attempts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('work_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by_name', sa.String(length=255), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_repair_request_attempts_work_order_id'),
        'repair_request_attempts',
        ['work_order_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_repair_request_attempts_work_order_id'), table_name='repair_request_attempts'
    )
    op.drop_table('repair_request_attempts')
    op.drop_column('work_orders', 'request_disqualify_comment')
    op.drop_column('work_orders', 'request_disqualify_reason')
    op.drop_column('work_orders', 'request_disqualified_by')
    op.drop_column('work_orders', 'request_disqualified_at')
    op.drop_column('role_tab_visibility', 'request_disqualify_unchecked')
    op.drop_column('app_settings', 'request_auto_disqualify_days')
    op.drop_column('app_settings', 'request_popup_interval_minutes')
    op.drop_column('app_settings', 'request_popup_enabled')
    op.drop_column('app_settings', 'request_min_talk_sec')
    op.drop_column('app_settings', 'request_second_call_days')
    op.drop_column('app_settings', 'request_first_call_days')
    op.drop_column('app_settings', 'request_control_enabled')
