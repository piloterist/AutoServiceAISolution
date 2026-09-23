"""add employees

Revision ID: f805aa4bd9aa
Revises: e9a12a2ec01c
Create Date: 2026-09-23 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f805aa4bd9aa'
down_revision: Union[str, None] = 'e9a12a2ec01c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('employees',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('specialty', sa.String(length=50), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('workshop_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_employees_department_id_departments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], name=op.f('fk_employees_workshop_id_workshops'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employees'))
    )


def downgrade() -> None:
    op.drop_table('employees')
