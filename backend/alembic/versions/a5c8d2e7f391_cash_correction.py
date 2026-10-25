"""cash correction right (Корректировка кассы)

Revision ID: a5c8d2e7f391
Revises: e3b9a41c7d52
Create Date: 2026-10-25 00:00:00.000000

Adds role_tab_visibility.cash_correction: only roles with it may create,
change or delete cash entries for days other than today. Seeded true for the
roles that manage money (Админ, Управляющий, Бухгалтер) so nobody who could
fix an old entry loses that on shipping; everyone else is today-only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5c8d2e7f391'
down_revision: Union[str, None] = 'e3b9a41c7d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'role_tab_visibility',
        sa.Column('cash_correction', sa.Boolean(), server_default='false', nullable=False),
    )
    op.execute(
        "UPDATE role_tab_visibility SET cash_correction = true "
        "WHERE role IN ('Админ', 'Управляющий', 'Бухгалтер')"
    )


def downgrade() -> None:
    op.drop_column('role_tab_visibility', 'cash_correction')
