"""raw transcript column for comparison

Revision ID: ab6e8104ae2f
Revises: 5300248ae8df
Create Date: 2026-10-05 13:05:09.101004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab6e8104ae2f'
down_revision: Union[str, None] = '5300248ae8df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("telephony_calls", sa.Column("transcript_text_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("telephony_calls", "transcript_text_raw")
