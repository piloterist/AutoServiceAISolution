"""transcript rewrite toggle

Revision ID: e5f95fa648a4
Revises: b8626caad6c0
Create Date: 2026-10-07 08:03:10.309770

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f95fa648a4"
down_revision: Union[str, None] = "b8626caad6c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telephony_settings",
        sa.Column(
            "transcript_rewrite_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("telephony_settings", "transcript_rewrite_enabled")
