"""bay_latest_frames: the latest frame of a bay, posted by the on-site node every minute

Revision ID: c9e5a2b7d836
Revises: b8d4f1a6c725
Create Date: 2026-11-04 10:00:00.000000

The node snapshots every bay once a minute. The page shows the frame in the "now" slot (and, for a
bay that has been empty for a while, in all three slots), so a missed exit is visible at once.
One row per bay: a new frame replaces the previous one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9e5a2b7d836'
down_revision: Union[str, None] = 'b8d4f1a6c725'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bay_latest_frames',
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('bay_id'),
    )


def downgrade() -> None:
    op.drop_table('bay_latest_frames')
