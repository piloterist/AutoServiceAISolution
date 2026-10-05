"""planner search exclude closed orders

Revision ID: 8efeed094dce
Revises: ab6e8104ae2f
Create Date: 2026-10-05 19:33:03.092769

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8efeed094dce"
down_revision: Union[str, None] = "ab6e8104ae2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "planner_search_exclude_closed_orders",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "planner_search_exclude_closed_orders")
