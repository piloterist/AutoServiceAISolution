"""add budget_entries

Revision ID: 1fc55af48b7b
Revises: 6812c17f6d90
Create Date: 2026-10-03 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fc55af48b7b'
down_revision: Union[str, None] = '6812c17f6d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'budget_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workshop_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('plan_revenue', sa.Numeric(14, 2), nullable=True),
        sa.Column('expenses', sa.Numeric(14, 2), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workshop_id', 'year', 'month', name='uq_budget_entry_period'),
    )
    op.create_index(op.f('ix_budget_entries_workshop_id'), 'budget_entries', ['workshop_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_budget_entries_workshop_id'), table_name='budget_entries')
    op.drop_table('budget_entries')
