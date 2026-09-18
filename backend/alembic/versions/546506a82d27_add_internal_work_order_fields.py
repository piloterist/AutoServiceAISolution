"""add internal work order fields

Revision ID: 546506a82d27
Revises: 533e415c595d
Create Date: 2026-09-18 08:16:02.920497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '546506a82d27'
down_revision: Union[str, None] = '533e415c595d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("vin", sa.String(length=32), nullable=True))
    op.add_column("work_orders", sa.Column("car_key", sa.String(length=17), nullable=True))
    op.create_index(op.f("ix_work_orders_car_key"), "work_orders", ["car_key"], unique=False)
    op.add_column(
        "work_orders",
        sa.Column(
            "is_internal", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.create_index(op.f("ix_work_orders_is_internal"), "work_orders", ["is_internal"], unique=False)

    op.add_column(
        "app_settings",
        sa.Column(
            "exclude_internal_orders", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "hide_internal_orders", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "hide_internal_orders")
    op.drop_column("app_settings", "exclude_internal_orders")

    op.drop_index(op.f("ix_work_orders_is_internal"), table_name="work_orders")
    op.drop_column("work_orders", "is_internal")
    op.drop_index(op.f("ix_work_orders_car_key"), table_name="work_orders")
    op.drop_column("work_orders", "car_key")
    op.drop_column("work_orders", "vin")
