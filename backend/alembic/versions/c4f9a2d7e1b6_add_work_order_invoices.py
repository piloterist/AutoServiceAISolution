"""add work order invoices

Revision ID: c4f9a2d7e1b6
Revises: b7d4f1a8c3e5
Create Date: 2026-09-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f9a2d7e1b6'
down_revision: Union[str, None] = 'b7d4f1a8c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_order_invoices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('work_order_id', sa.UUID(), nullable=False),
    sa.Column('source_document_id', sa.String(length=100), nullable=False),
    sa.Column('external_number', sa.String(length=100), nullable=True),
    sa.Column('document_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('debt_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('posted', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name=op.f('fk_work_order_invoices_work_order_id_work_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_invoices')),
    sa.UniqueConstraint('source_document_id', name=op.f('uq_work_order_invoices_source_document_id'))
    )
    op.create_index(op.f('ix_work_order_invoices_work_order_id'), 'work_order_invoices', ['work_order_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_work_order_invoices_work_order_id'), table_name='work_order_invoices')
    op.drop_table('work_order_invoices')
