"""add employee to workshop_jobs

Revision ID: a60cd9ebd165
Revises: bed0f940c7ad
Create Date: 2026-09-23 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a60cd9ebd165'
down_revision: Union[str, None] = 'bed0f940c7ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workshop_jobs', sa.Column('employee_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('fk_workshop_jobs_employee_id_employees'),
        'workshop_jobs',
        'employees',
        ['employee_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_workshop_jobs_employee_id_employees'), 'workshop_jobs', type_='foreignkey'
    )
    op.drop_column('workshop_jobs', 'employee_id')
