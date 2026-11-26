"""app_settings.allocate_external: "Аллоцировать внешние" (Специфика PanMotors)

Revision ID: d4b8e1f6a3c7
Revises: a3f9c1d7e5b2
Create Date: 2026-11-26 15:00:00.000000

Бюджеты: выручка страхового заказ-наряда делится между цехами его внутренних
заказ-нарядов пропорционально их суммам (services/insurance_allocation.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b8e1f6a3c7'
down_revision: Union[str, None] = 'a3f9c1d7e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('allocate_external', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'allocate_external')
