"""add organization to work orders

Revision ID: cc7d74aeaf6f
Revises: f731d5f500da
Create Date: 2026-09-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc7d74aeaf6f'
down_revision: Union[str, None] = 'f731d5f500da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column('organization', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('work_orders', 'organization')
