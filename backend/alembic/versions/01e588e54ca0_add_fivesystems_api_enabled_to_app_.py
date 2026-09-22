"""add fivesystems api enabled to app settings

Revision ID: 01e588e54ca0
Revises: 1e1aba094f72
Create Date: 2026-09-22 08:43:43.152932

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01e588e54ca0'
down_revision: Union[str, None] = '1e1aba094f72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column(
            'fivesystems_api_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'fivesystems_api_enabled')
