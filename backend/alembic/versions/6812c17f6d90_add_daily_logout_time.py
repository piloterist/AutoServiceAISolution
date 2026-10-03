"""add daily_logout_time

Revision ID: 6812c17f6d90
Revises: 006d139a8ae5
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6812c17f6d90'
down_revision: Union[str, None] = '006d139a8ae5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the existing singleton app_settings row (see
    # services/settings_service.py) doesn't violate NOT NULL.
    op.add_column(
        'app_settings',
        sa.Column('daily_logout_time', sa.String(length=5), server_default='23:30', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'daily_logout_time')
