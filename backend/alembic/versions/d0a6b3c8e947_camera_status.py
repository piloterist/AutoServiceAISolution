"""camera_status: heartbeat of the on-site node per camera

Revision ID: d0a6b3c8e947
Revises: c9e5a2b7d836
Create Date: 2026-11-04 15:00:00.000000

The node posts a heartbeat every ~30 s per camera: it is alive and the camera does (not) deliver
video. The page shows "node offline for N min" / "camera unavailable for N min" from this row,
so a switched-off node no longer looks like a bay that is simply quiet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0a6b3c8e947'
down_revision: Union[str, None] = 'c9e5a2b7d836'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'camera_status',
        sa.Column('camera_code', sa.String(length=50), nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('camera_ok', sa.Boolean(), nullable=False),
        sa.Column('camera_ok_since', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detail', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('camera_code'),
    )


def downgrade() -> None:
    op.drop_table('camera_status')
