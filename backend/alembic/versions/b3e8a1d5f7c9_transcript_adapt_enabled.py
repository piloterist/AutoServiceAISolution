"""transcript adapt setting (лёгкая правка расшифровки отдельной галкой, по умолчанию выключена)

Revision ID: b3e8a1d5f7c9
Revises: a9d3f7b1c5e2
Create Date: 2026-11-18 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e8a1d5f7c9'
down_revision: Union[str, None] = 'a9d3f7b1c5e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'telephony_settings',
        sa.Column('transcript_adapt_enabled', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('telephony_settings', 'transcript_adapt_enabled')
