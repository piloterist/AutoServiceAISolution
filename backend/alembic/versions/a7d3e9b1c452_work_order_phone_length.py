"""work_orders.phone: widen from 30 to 200 characters

Revision ID: a7d3e9b1c452
Revises: f6a2c8d1e395
Create Date: 2026-10-27 15:00:00.000000

Old work orders (inside the 400-day export window) carry several phone
numbers / a note in 1C's phone field, longer than 30 characters; the chunk
holding such a record failed with StringDataRightTruncation and the whole
Yandex.Disk file was re-imported on every poll.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e9b1c452'
down_revision: Union[str, None] = 'f6a2c8d1e395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'work_orders', 'phone',
        existing_type=sa.String(length=30), type_=sa.String(length=200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'work_orders', 'phone',
        existing_type=sa.String(length=200), type_=sa.String(length=30),
        existing_nullable=True,
    )
