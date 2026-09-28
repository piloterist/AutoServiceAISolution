"""add theme to users

Revision ID: a3c1e6d9f2b4
Revises: 47f527c9b970
Create Date: 2026-09-25 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c1e6d9f2b4'
down_revision: Union[str, None] = '47f527c9b970'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('theme', sa.String(length=10), nullable=False, server_default='light'),
    )


def downgrade() -> None:
    op.drop_column('users', 'theme')
