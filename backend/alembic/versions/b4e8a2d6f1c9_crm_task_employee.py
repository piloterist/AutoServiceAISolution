"""crm_tasks.employee_id (сотрудник, ответственный за карточку доски задач)

Revision ID: b4e8a2d6f1c9
Revises: a3d7f1c9e5b8
Create Date: 2026-11-15 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4e8a2d6f1c9'
down_revision: Union[str, None] = 'a3d7f1c9e5b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_tasks', sa.Column('employee_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_crm_tasks_employee_id', 'crm_tasks', 'employees', ['employee_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(op.f('ix_crm_tasks_employee_id'), 'crm_tasks', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_crm_tasks_employee_id'), table_name='crm_tasks')
    op.drop_constraint('fk_crm_tasks_employee_id', 'crm_tasks', type_='foreignkey')
    op.drop_column('crm_tasks', 'employee_id')
