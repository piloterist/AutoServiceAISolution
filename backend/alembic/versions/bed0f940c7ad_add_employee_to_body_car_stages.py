"""add employee to body_car_stages

Revision ID: bed0f940c7ad
Revises: fd2d050e46b2
Create Date: 2026-09-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bed0f940c7ad'
down_revision: Union[str, None] = 'fd2d050e46b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('body_car_stages', sa.Column('employee_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('fk_body_car_stages_employee_id_employees'),
        'body_car_stages',
        'employees',
        ['employee_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_body_car_stages_employee_id_employees'), 'body_car_stages', type_='foreignkey'
    )
    op.drop_column('body_car_stages', 'employee_id')
