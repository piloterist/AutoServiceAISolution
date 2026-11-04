"""bays, bay_events, bay_occupancy, bay_snapshot_requests (video control of bays)

Revision ID: a7c3e9d2b514
Revises: e2b7c5d9f416
Create Date: 2026-11-03 16:00:00.000000

Purely additive: four new tables, nothing existing is touched, so the previous
release keeps working while a deploy is rolling out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d2b514'
down_revision: Union[str, None] = 'e2b7c5d9f416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bays',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workshop_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('camera_code', sa.String(length=50), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], name=op.f('fk_bays_workshop_id_workshops'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bays')),
    )
    op.create_index(op.f('ix_bays_workshop_id'), 'bays', ['workshop_id'], unique=False)

    op.create_table(
        'bay_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('plate', sa.String(length=20), nullable=True),
        sa.Column('ocr_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('snapshot_path', sa.String(length=300), nullable=True),
        sa.Column('work_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('review_status', sa.String(length=20), server_default='auto', nullable=False),
        sa.Column('source', sa.String(length=10), server_default='auto', nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], name=op.f('fk_bay_events_bay_id_bays'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name=op.f('fk_bay_events_work_order_id_work_orders'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bay_events')),
    )
    op.create_index(op.f('ix_bay_events_bay_id'), 'bay_events', ['bay_id'], unique=False)

    op.create_table(
        'bay_occupancy',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plate', sa.String(length=20), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entry_event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exit_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('review_status', sa.String(length=20), server_default='auto', nullable=False),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], name=op.f('fk_bay_occupancy_bay_id_bays'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entry_event_id'], ['bay_events.id'], name=op.f('fk_bay_occupancy_entry_event_id_bay_events'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exit_event_id'], ['bay_events.id'], name=op.f('fk_bay_occupancy_exit_event_id_bay_events'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bay_occupancy')),
    )
    op.create_index(op.f('ix_bay_occupancy_bay_id'), 'bay_occupancy', ['bay_id'], unique=False)

    op.create_table(
        'bay_snapshot_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('snapshot_path', sa.String(length=300), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], name=op.f('fk_bay_snapshot_requests_bay_id_bays'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bay_snapshot_requests')),
    )
    op.create_index(op.f('ix_bay_snapshot_requests_bay_id'), 'bay_snapshot_requests', ['bay_id'], unique=False)


def downgrade() -> None:
    op.drop_table('bay_snapshot_requests')
    op.drop_table('bay_occupancy')
    op.drop_table('bay_events')
    op.drop_table('bays')
