"""cameras.mode: бокс или ворота (по нему узел заводит камеру, найденную по MAC)

Revision ID: a8f3c5d1e7b2
Revises: f6d1a8c3e2b5
Create Date: 2026-11-27 17:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f3c5d1e7b2'
down_revision: Union[str, None] = 'f6d1a8c3e2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cameras',
        sa.Column('mode', sa.String(length=10), nullable=False, server_default='bay'),
    )


def downgrade() -> None:
    op.drop_column('cameras', 'mode')
