"""work_order_payment_events.is_fictitious: «Фиктивные» платежи (дубли строк одного платежа)

Revision ID: e5c9f2a7b1d4
Revises: d4b8e1f6a3c7
Create Date: 2026-11-27 14:00:00.000000

Пометка ставится services/payment_duplicates.py (при импорте и разовой прогонкой);
фиктивные платежи не учитываются в суммах, проценте оплаты и Бюджетах.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c9f2a7b1d4'
down_revision: Union[str, None] = 'd4b8e1f6a3c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'work_order_payment_events',
        sa.Column('is_fictitious', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('work_order_payment_events', 'is_fictitious')
