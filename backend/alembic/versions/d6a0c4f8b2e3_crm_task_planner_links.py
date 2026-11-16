"""crm task planner record links (запись планировщика, с которой связана карточка)

Revision ID: d6a0c4f8b2e3
Revises: c5f9b3e7a2d1
Create Date: 2026-11-16 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd6a0c4f8b2e3'
down_revision: Union[str, None] = 'c5f9b3e7a2d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_tasks', sa.Column('body_car_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        'crm_tasks', sa.Column('workshop_job_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_crm_tasks_body_car_id', 'crm_tasks', 'body_cars', ['body_car_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_crm_tasks_workshop_job_id', 'crm_tasks', 'workshop_jobs', ['workshop_job_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_crm_tasks_workshop_job_id', 'crm_tasks', type_='foreignkey')
    op.drop_constraint('fk_crm_tasks_body_car_id', 'crm_tasks', type_='foreignkey')
    op.drop_column('crm_tasks', 'workshop_job_id')
    op.drop_column('crm_tasks', 'body_car_id')
