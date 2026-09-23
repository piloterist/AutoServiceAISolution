"""add phone to work_orders, workshop_jobs, body_cars

Revision ID: e9a12a2ec01c
Revises: 01e588e54ca0
Create Date: 2026-09-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a12a2ec01c'
down_revision: Union[str, None] = '01e588e54ca0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column('phone', sa.String(length=30), nullable=True))
    op.add_column('workshop_jobs', sa.Column('phone', sa.String(length=30), nullable=True))
    op.add_column('body_cars', sa.Column('phone', sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column('body_cars', 'phone')
    op.drop_column('workshop_jobs', 'phone')
    op.drop_column('work_orders', 'phone')
