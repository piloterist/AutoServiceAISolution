"""settings: virtual repair types (Виртуальные)

Revision ID: c9d3a6e1b784
Revises: b7e1f4a9c256
Create Date: 2026-10-25 00:00:00.000000

app_settings.virtual_repair_types: repair types that, like the warranty ones,
never count as revenue on any tab.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d3a6e1b784'
down_revision: Union[str, None] = 'b7e1f4a9c256'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('virtual_repair_types', sa.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'virtual_repair_types')
