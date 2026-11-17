"""crm tasks from website leads (задача на доске может быть взята с заявки с сайта)

Revision ID: f8c2e6b0d4a5
Revises: e7b1d5a9c3f4
Create Date: 2026-11-17 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f8c2e6b0d4a5'
down_revision: Union[str, None] = 'e7b1d5a9c3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_tasks', sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_crm_tasks_lead_id', 'crm_tasks', 'website_leads', ['lead_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_crm_tasks_lead_id', 'crm_tasks', type_='foreignkey')
    op.drop_column('crm_tasks', 'lead_id')
