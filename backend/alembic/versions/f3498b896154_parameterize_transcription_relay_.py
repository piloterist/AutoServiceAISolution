"""parameterize transcription relay interval and batch size

Revision ID: f3498b896154
Revises: 33e29c7d85a4
Create Date: 2026-10-04 15:25:22.931440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3498b896154'
down_revision: Union[str, None] = '33e29c7d85a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telephony_settings",
        sa.Column(
            "transcription_poll_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
    )
    op.add_column(
        "telephony_settings",
        sa.Column("transcription_batch_size", sa.Integer(), nullable=False, server_default="20"),
    )


def downgrade() -> None:
    op.drop_column("telephony_settings", "transcription_batch_size")
    op.drop_column("telephony_settings", "transcription_poll_interval_minutes")
