"""cost items: hand-set order

Revision ID: e5f1a7c3b284
Revises: d4e8b2f6a193
Create Date: 2026-10-26 00:00:00.000000

cost_items.sort_order: the order set by dragging rows in Настройки -> Финансы
(and used by Финансы -> Расходы). Existing items keep today's alphabetical
order as their starting point.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f1a7c3b284'
down_revision: Union[str, None] = 'd4e8b2f6a193'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cost_items',
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    )
    op.execute(
        "UPDATE cost_items SET sort_order = ranked.position FROM ("
        "SELECT id, row_number() OVER (ORDER BY name) AS position FROM cost_items"
        ") AS ranked WHERE cost_items.id = ranked.id"
    )


def downgrade() -> None:
    op.drop_column('cost_items', 'sort_order')
