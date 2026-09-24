"""add on_site to body_cars

Revision ID: 47f527c9b970
Revises: c867c16432af
Create Date: 2026-09-24 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47f527c9b970'
down_revision: Union[str, None] = 'c867c16432af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'body_cars',
        sa.Column('on_site', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('body_cars', 'on_site')
