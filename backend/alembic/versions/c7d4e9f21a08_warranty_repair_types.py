"""warranty repair types (Специфика PanMotors)

Revision ID: c7d4e9f21a08
Revises: a3aaf2a4bf60
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d4e9f21a08'
down_revision: Union[str, None] = 'a3aaf2a4bf60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "warranty_repair_types",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "warranty_repair_types")
