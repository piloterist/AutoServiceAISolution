"""add planning fields to workshops

Revision ID: d8e3b5c1f9a7
Revises: c4f9a2d7e1b6
Create Date: 2026-09-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e3b5c1f9a7'
down_revision: Union[str, None] = 'c4f9a2d7e1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workshops', sa.Column('zero_revenue', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('workshops', sa.Column('target_revenue', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('workshops', sa.Column('target_norm_hours', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('workshops', 'target_norm_hours')
    op.drop_column('workshops', 'target_revenue')
    op.drop_column('workshops', 'zero_revenue')
