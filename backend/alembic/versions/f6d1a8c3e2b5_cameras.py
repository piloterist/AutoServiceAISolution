"""cameras: справочник камер (код, MAC, модель, текущий IP от узла)

Revision ID: f6d1a8c3e2b5
Revises: e5c9f2a7b1d4
Create Date: 2026-11-27 16:00:00.000000

Настройки -> Камеры. Узел находит IP камеры по MAC и присылает его в сигнале «я на связи».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6d1a8c3e2b5'
down_revision: Union[str, None] = 'e5c9f2a7b1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cameras',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('mac', sa.String(length=17), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('ip_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint('code', name='uq_cameras_code'),
        sa.UniqueConstraint('mac', name='uq_cameras_mac'),
    )


def downgrade() -> None:
    op.drop_table('cameras')
