"""control posts setting (Контролировать посты)

Revision ID: a9d3f7b1c5e2
Revises: f8c2e6b0d4a5
Create Date: 2026-11-18 16:00:00.000000

Off (default): a camera's plate is looked up on every post of the workshop and the found plan
record is started on the post where it was made; on: only the camera's own post is searched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d3f7b1c5e2'
down_revision: Union[str, None] = 'f8c2e6b0d4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('control_posts_enabled', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'control_posts_enabled')
