"""add speechkit settings to telephony_settings

Revision ID: f2a6c8e1d4b7
Revises: e1f4a7c2b8d3
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a6c8e1d4b7'
down_revision: Union[str, None] = 'e1f4a7c2b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('telephony_settings', sa.Column('zeon_audio_method', sa.String(length=10), server_default='get-mp3', nullable=False))
    op.add_column('telephony_settings', sa.Column('yc_api_key', sa.String(length=255), nullable=True))
    op.add_column('telephony_settings', sa.Column('yc_folder_id', sa.String(length=50), nullable=True))
    op.add_column('telephony_settings', sa.Column('speechkit_model', sa.String(length=30), server_default='general', nullable=False))
    op.add_column('telephony_settings', sa.Column('speechkit_language', sa.String(length=10), server_default='ru-RU', nullable=False))
    op.add_column('telephony_settings', sa.Column('speechkit_timeout_min', sa.Integer(), server_default='60', nullable=False))


def downgrade() -> None:
    op.drop_column('telephony_settings', 'speechkit_timeout_min')
    op.drop_column('telephony_settings', 'speechkit_language')
    op.drop_column('telephony_settings', 'speechkit_model')
    op.drop_column('telephony_settings', 'yc_folder_id')
    op.drop_column('telephony_settings', 'yc_api_key')
    op.drop_column('telephony_settings', 'zeon_audio_method')
