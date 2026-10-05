"""planner auto match by phone or vin

Revision ID: 5300248ae8df
Revises: f3498b896154
Create Date: 2026-10-05 10:34:39.342704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5300248ae8df'
down_revision: Union[str, None] = 'f3498b896154'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "planner_auto_match_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "planner_auto_match_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="180",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "planner_auto_match_interval_minutes")
    op.drop_column("app_settings", "planner_auto_match_enabled")
