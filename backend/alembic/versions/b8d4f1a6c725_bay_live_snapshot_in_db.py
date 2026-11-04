"""bay_snapshot_requests: keep the live frame in the database instead of Yandex.Disk

Revision ID: b8d4f1a6c725
Revises: a7c3e9d2b514
Create Date: 2026-11-03 18:00:00.000000

The "Получить кадр" frame is short-lived, so storing it on Yandex.Disk only added a slow,
sometimes failing round trip. The snapshot_path column of a request was never used by
anything but that path, so it is replaced by the image itself. Event snapshots (entry /
exit) stay on Yandex.Disk.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d4f1a6c725'
down_revision: Union[str, None] = 'a7c3e9d2b514'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bay_snapshot_requests', sa.Column('image', sa.LargeBinary(), nullable=True))
    op.drop_column('bay_snapshot_requests', 'snapshot_path')


def downgrade() -> None:
    op.add_column('bay_snapshot_requests', sa.Column('snapshot_path', sa.String(length=300), nullable=True))
    op.drop_column('bay_snapshot_requests', 'image')
