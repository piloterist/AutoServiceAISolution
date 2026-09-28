"""convert telephony poll interval to minutes

Revision ID: b77e8b85ed0a
Revises: a4e7f1c9b3d2
Create Date: 2026-09-28 14:34:19.845235

Renames telephony_settings.poll_interval_hours to poll_interval_minutes and
scales any existing non-null value by 60, so an operator's already-configured
schedule keeps meaning the same real-world interval across the rename - a
pure unit change, not a behavior change. See app/services/telephony_relay.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b77e8b85ed0a'
down_revision: Union[str, None] = 'a4e7f1c9b3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'telephony_settings', 'poll_interval_hours', new_column_name='poll_interval_minutes'
    )
    op.execute(
        "UPDATE telephony_settings SET poll_interval_minutes = poll_interval_minutes * 60 "
        "WHERE poll_interval_minutes IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE telephony_settings SET poll_interval_minutes = poll_interval_minutes / 60 "
        "WHERE poll_interval_minutes IS NOT NULL"
    )
    op.alter_column(
        'telephony_settings', 'poll_interval_minutes', new_column_name='poll_interval_hours'
    )
