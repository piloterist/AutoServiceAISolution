"""work order lines: discount and total after the discount

Revision ID: f6a2c8d1e395
Revises: e5f1a7c3b284
Create Date: 2026-10-28 00:00:00.000000

work_order_labor_lines / work_order_part_lines get discount_percent (1C ПроцентСкидки),
discount_amount (1C СуммаСкидки), discount_name (the discount's name) and total_amount (1C СуммаВсего - the line AFTER its discount). The old "amount"
is the line before the discount, so Работы + Запчасти did not add up to the
document amount; the Бюджеты sub-rows now use total_amount. Filled by the next
export from 1C; NULL until then.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a2c8d1e395'
down_revision: Union[str, None] = 'e5f1a7c3b284'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('work_order_labor_lines', 'work_order_part_lines'):
        op.add_column(table, sa.Column('discount_percent', sa.Numeric(7, 2), nullable=True))
        op.add_column(table, sa.Column('discount_amount', sa.Numeric(14, 2), nullable=True))
        op.add_column(table, sa.Column('total_amount', sa.Numeric(14, 2), nullable=True))
        op.add_column(table, sa.Column('discount_name', sa.String(length=200), nullable=True))


def downgrade() -> None:
    for table in ('work_order_labor_lines', 'work_order_part_lines'):
        op.drop_column(table, 'discount_name')
        op.drop_column(table, 'total_amount')
        op.drop_column(table, 'discount_amount')
        op.drop_column(table, 'discount_percent')
