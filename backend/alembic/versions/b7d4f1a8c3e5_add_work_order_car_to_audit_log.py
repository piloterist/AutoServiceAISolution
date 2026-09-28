"""add work_order_id and car_description to schedule_audit_log

Revision ID: b7d4f1a8c3e5
Revises: a3c1e6d9f2b4
Create Date: 2026-09-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4f1a8c3e5'
down_revision: Union[str, None] = 'a3c1e6d9f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('schedule_audit_log', sa.Column('work_order_id', sa.UUID(), nullable=True))
    op.add_column(
        'schedule_audit_log',
        sa.Column('car_description', sa.String(length=500), nullable=True),
    )
    op.create_foreign_key(
        op.f('fk_schedule_audit_log_work_order_id_work_orders'),
        'schedule_audit_log',
        'work_orders',
        ['work_order_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_schedule_audit_log_work_order_id_work_orders'),
        'schedule_audit_log',
        type_='foreignkey',
    )
    op.drop_column('schedule_audit_log', 'car_description')
    op.drop_column('schedule_audit_log', 'work_order_id')
