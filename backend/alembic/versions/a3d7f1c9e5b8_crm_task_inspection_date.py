"""crm_tasks: inspection_date / inspection_end_date (дата осмотра на карточке)

Revision ID: a3d7f1c9e5b8
Revises: f5b2d8e1a7c3
Create Date: 2026-11-15 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3d7f1c9e5b8'
down_revision: Union[str, None] = 'f5b2d8e1a7c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_tasks', sa.Column('inspection_date', sa.Date(), nullable=True))
    op.add_column('crm_tasks', sa.Column('inspection_end_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('crm_tasks', 'inspection_end_date')
    op.drop_column('crm_tasks', 'inspection_date')
