"""work_orders: doc_type and linked_work_orders (repair requests)

Revision ID: b8e4f2a6d193
Revises: a7d3e9b1c452
Create Date: 2026-10-27 18:00:00.000000

Repair requests (1C: Заявка на ремонт) are stored next to the work orders:
doc_type tells them apart ("work_order" for every existing row),
linked_work_orders lists the work orders created from a request.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4f2a6d193'
down_revision: Union[str, None] = 'a7d3e9b1c452'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'work_orders',
        sa.Column('doc_type', sa.String(length=20), nullable=False, server_default='work_order'),
    )
    op.add_column('work_orders', sa.Column('linked_work_orders', sa.String(length=500), nullable=True))
    op.create_index(op.f('ix_work_orders_doc_type'), 'work_orders', ['doc_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_work_orders_doc_type'), table_name='work_orders')
    op.drop_column('work_orders', 'linked_work_orders')
    op.drop_column('work_orders', 'doc_type')
