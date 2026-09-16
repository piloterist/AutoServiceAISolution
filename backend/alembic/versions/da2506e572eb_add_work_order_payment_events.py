"""add work order payment events

Revision ID: da2506e572eb
Revises: 3a785672624b
Create Date: 2026-09-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da2506e572eb'
down_revision: Union[str, None] = '3a785672624b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_order_payment_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('work_order_id', sa.UUID(), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('source_document_id', sa.String(length=100), nullable=False),
    sa.Column('source_document_type', sa.String(length=150), nullable=True),
    sa.Column('source_document_number', sa.String(length=100), nullable=True),
    sa.Column('line_number', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name=op.f('fk_work_order_payment_events_work_order_id_work_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_payment_events')),
    sa.UniqueConstraint('work_order_id', 'source_document_id', 'line_number', name='uq_work_order_payment_events_document_line')
    )
    op.create_index(op.f('ix_work_order_payment_events_paid_at'), 'work_order_payment_events', ['paid_at'], unique=False)
    op.create_index(op.f('ix_work_order_payment_events_work_order_id'), 'work_order_payment_events', ['work_order_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_work_order_payment_events_work_order_id'), table_name='work_order_payment_events')
    op.drop_index(op.f('ix_work_order_payment_events_paid_at'), table_name='work_order_payment_events')
    op.drop_table('work_order_payment_events')
