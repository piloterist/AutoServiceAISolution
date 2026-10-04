"""widen call topic summary column

Revision ID: 33e29c7d85a4
Revises: 6a9dbc9750fa
Create Date: 2026-10-04 14:22:49.966342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33e29c7d85a4'
down_revision: Union[str, None] = '6a9dbc9750fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # telephony_calls.topic_tag used to hold a fixed 3-value tag
    # (Кузовной/Слесарный/Не определено, max 9 chars) - now holds a short
    # free-text call summary (e.g. "Стоимость замены колодок на Chery
    # Tiggo 8"), up to ~200 chars - see models/call_record.py.
    op.alter_column(
        "telephony_calls",
        "topic_tag",
        existing_type=sa.String(length=20),
        type_=sa.String(length=200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "telephony_calls",
        "topic_tag",
        existing_type=sa.String(length=200),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
