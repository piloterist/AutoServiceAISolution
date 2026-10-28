"""app_settings.receivables_max_age_days: hide receivables older than N days

Revision ID: e2b7c5d9f416
Revises: d1a6b4c8e305
Create Date: 2026-10-29 12:00:00.000000

NULL = no limit (nothing is hidden), so the previous release keeps working while a
deploy is rolling out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7c5d9f416'
down_revision: Union[str, None] = 'd1a6b4c8e305'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('receivables_max_age_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'receivables_max_age_days')
