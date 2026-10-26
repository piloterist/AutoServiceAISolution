"""cost items (статьи затрат) and monthly expenses per workshop

Revision ID: d4e8b2f6a193
Revises: c9d3a6e1b784
Create Date: 2026-10-26 00:00:00.000000

cost_items: the Настройки -> Финансы directory (name + active flag).
cost_expenses: an amount per (cost item, workshop, year, month) - the
Финансы -> Расходы table; its monthly total per workshop is the Бюджет
"Расходы" row (the old manually-entered budget_entries.expenses is no longer
read, but is left in place).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b2f6a193'
down_revision: Union[str, None] = 'c9d3a6e1b784'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cost_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'cost_expenses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('cost_item_id', sa.UUID(), nullable=False),
        sa.Column('workshop_id', sa.UUID(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['cost_item_id'], ['cost_items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cost_item_id', 'workshop_id', 'year', 'month', name='uq_cost_expense_cell'),
    )
    op.create_index(op.f('ix_cost_expenses_cost_item_id'), 'cost_expenses', ['cost_item_id'])
    op.create_index(op.f('ix_cost_expenses_workshop_id'), 'cost_expenses', ['workshop_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_cost_expenses_workshop_id'), table_name='cost_expenses')
    op.drop_index(op.f('ix_cost_expenses_cost_item_id'), table_name='cost_expenses')
    op.drop_table('cost_expenses')
    op.drop_table('cost_items')
