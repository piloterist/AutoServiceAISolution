"""ворота кузовного цеха: bays.kind и таблица gate_stays (машина в цехе от въезда до выезда)

Revision ID: c7d2a9e4f1b8
Revises: b3e8a1d5f7c9
Create Date: 2026-11-19 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d2a9e4f1b8'
down_revision: Union[str, None] = 'b3e8a1d5f7c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bays', sa.Column('kind', sa.String(length=10), server_default='bay', nullable=False))
    op.create_table(
        'gate_stays',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plate', sa.String(length=20), nullable=True),
        sa.Column('label', sa.String(length=200), nullable=True),
        sa.Column('entered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entry_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('exited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exit_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('body_car_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('work_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('review_status', sa.String(length=20), server_default='auto', nullable=False),
        sa.Column('source', sa.String(length=10), server_default='auto', nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entry_event_id'], ['bay_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exit_event_id'], ['bay_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['body_car_id'], ['body_cars.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_gate_stays_bay_id', 'gate_stays', ['bay_id'])


def downgrade() -> None:
    op.drop_index('ix_gate_stays_bay_id', table_name='gate_stays')
    op.drop_table('gate_stays')
    op.drop_column('bays', 'kind')
