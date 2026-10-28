"""app_settings.order_exclusion_mode: "Исключить" = none / internal / external

Revision ID: c9f5a3b7d204
Revises: b8e4f2a6d193
Create Date: 2026-10-28 15:00:00.000000

Replaces the boolean exclude_internal_orders: the old checkbox becomes
"internal", unchecked becomes "none"; the new "external" excludes the
insurance repair type. The old column is deliberately left in place (unused
by the code now): dropping it would break the previous release while a deploy
is still rolling out. The downgrade writes the mode back into it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f5a3b7d204'
down_revision: Union[str, None] = 'b8e4f2a6d193'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('order_exclusion_mode', sa.String(length=10), nullable=False, server_default='none'),
    )
    op.execute("UPDATE app_settings SET order_exclusion_mode = 'internal' WHERE exclude_internal_orders")


def downgrade() -> None:
    op.execute("UPDATE app_settings SET exclude_internal_orders = (order_exclusion_mode = 'internal')")
    op.drop_column('app_settings', 'order_exclusion_mode')
