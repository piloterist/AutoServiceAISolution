"""crm task archive days (срок архива доски задач)

Revision ID: e4a1c7d3b9f2
Revises: d2f9b6a4c1e8
Create Date: 2026-11-15 12:00:00.000000

After this many days in the column, a card in "Отказ" / "Заказ-наряд" leaves the board for the
archive (shown with the "Показать архивные" checkbox).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a1c7d3b9f2'
down_revision: Union[str, None] = 'd2f9b6a4c1e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('crm_task_archive_days', sa.Integer(), server_default='30', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('app_settings', 'crm_task_archive_days')
