"""cash personal card + users.employee_id (a user is linked to an employee)

Revision ID: d1a6b4c8e305
Revises: c9f5a3b7d204
Create Date: 2026-10-29 10:00:00.000000

- users.employee_id: the Settings user may be linked to a row of the employees
  directory; an employee can be linked to at most one user (unique).
- cash_entries.personal_card / card_holder_id / card_holder_name: a "Приход НАЛ" /
  "Расход НАЛ" entry marked "Личная карта" and tied to an employee (a master-advisor
  of the directory). A person's card balance is simply their marked entries.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd1a6b4c8e305'
down_revision: Union[str, None] = 'c9f5a3b7d204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('employee_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_users_employee_id_employees', 'users', 'employees', ['employee_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_users_employee_id', 'users', ['employee_id'])

    op.add_column(
        'cash_entries',
        sa.Column('personal_card', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'cash_entries',
        sa.Column('card_holder_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'cash_entries',
        sa.Column('card_holder_name', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        'fk_cash_entries_card_holder_id_employees',
        'cash_entries', 'employees', ['card_holder_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        'ix_cash_entries_card_holder_id', 'cash_entries', ['card_holder_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_cash_entries_card_holder_id', table_name='cash_entries')
    op.drop_constraint('fk_cash_entries_card_holder_id_employees', 'cash_entries', type_='foreignkey')
    op.drop_column('cash_entries', 'card_holder_name')
    op.drop_column('cash_entries', 'card_holder_id')
    op.drop_column('cash_entries', 'personal_card')
    op.drop_constraint('uq_users_employee_id', 'users', type_='unique')
    op.drop_constraint('fk_users_employee_id_employees', 'users', type_='foreignkey')
    op.drop_column('users', 'employee_id')
