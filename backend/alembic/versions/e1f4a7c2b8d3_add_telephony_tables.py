"""add telephony tables

Revision ID: e1f4a7c2b8d3
Revises: d8e3b5c1f9a7
Create Date: 2026-09-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1f4a7c2b8d3'
down_revision: Union[str, None] = 'd8e3b5c1f9a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('telephony_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('zeon_api_url', sa.String(length=255), nullable=True),
    sa.Column('zeon_api_key', sa.String(length=255), nullable=True),
    sa.Column('zeon_auth', sa.String(length=10), nullable=False),
    sa.Column('yandex_disk_token', sa.String(length=255), nullable=True),
    sa.Column('yandex_disk_base_path', sa.String(length=255), nullable=True),
    sa.Column('operator_names', sa.String(length=2000), nullable=True),
    sa.Column('poll_interval_hours', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telephony_settings'))
    )

    op.create_table('phone_sources',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('line_code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('caption', sa.String(length=255), nullable=True),
    sa.Column('group_name', sa.String(length=50), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phone_sources')),
    sa.UniqueConstraint('line_code', name='uq_phone_sources_line_code')
    )

    op.create_table('telephony_calls',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=100), nullable=False),
    sa.Column('linkedid', sa.String(length=100), nullable=True),
    sa.Column('call_date', sa.Date(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('call_type', sa.String(length=10), nullable=False),
    sa.Column('client', sa.String(length=20), nullable=True),
    sa.Column('line', sa.String(length=100), nullable=True),
    sa.Column('operator', sa.String(length=20), nullable=True),
    sa.Column('rang_not_answered', postgresql.ARRAY(sa.String()), nullable=True),
    sa.Column('wait_sec', sa.Integer(), nullable=False),
    sa.Column('talk_sec', sa.Integer(), nullable=False),
    sa.Column('answered', sa.Boolean(), nullable=False),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telephony_calls')),
    sa.UniqueConstraint('provider', 'external_id', name='uq_telephony_calls_provider_external_id')
    )
    op.create_index(op.f('ix_telephony_calls_provider'), 'telephony_calls', ['provider'], unique=False)
    op.create_index(op.f('ix_telephony_calls_call_date'), 'telephony_calls', ['call_date'], unique=False)
    op.create_index(op.f('ix_telephony_calls_occurred_at'), 'telephony_calls', ['occurred_at'], unique=False)
    op.create_index(op.f('ix_telephony_calls_client'), 'telephony_calls', ['client'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_telephony_calls_client'), table_name='telephony_calls')
    op.drop_index(op.f('ix_telephony_calls_occurred_at'), table_name='telephony_calls')
    op.drop_index(op.f('ix_telephony_calls_call_date'), table_name='telephony_calls')
    op.drop_index(op.f('ix_telephony_calls_provider'), table_name='telephony_calls')
    op.drop_table('telephony_calls')
    op.drop_table('phone_sources')
    op.drop_table('telephony_settings')
