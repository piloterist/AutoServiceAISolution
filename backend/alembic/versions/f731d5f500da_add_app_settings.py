"""add app_settings

Revision ID: f731d5f500da
Revises: da2506e572eb
Create Date: 2026-09-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f731d5f500da'
down_revision: Union[str, None] = 'da2506e572eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('insurance_repair_type', sa.String(length=150), nullable=True),
    sa.Column('exclude_internal_insurance', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_settings'))
    )


def downgrade() -> None:
    op.drop_table('app_settings')
