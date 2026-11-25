"""bay_events.created_by_name - кто ввёл событие бокса вручную

Revision ID: a3f9c1d7e5b2
Revises: d4e8b1a7c3f5
Create Date: 2026-11-25 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9c1d7e5b2'
down_revision: Union[str, None] = 'd4e8b1a7c3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bay_events', sa.Column('created_by_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('bay_events', 'created_by_name')
