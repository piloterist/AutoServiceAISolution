"""add role_tab_visibility

Revision ID: fd2d050e46b2
Revises: f805aa4bd9aa
Create Date: 2026-09-23 10:10:00.000000

Seeds one row per existing role, matching exactly what the app already
did with the previous hardcoded rule (see frontend middleware.ts before
this migration) - Мастер приёмщик restricted to Планер only, every other
role unrestricted (all tabs). This is what makes shipping this migration
safe: nobody's visible tabs change on deploy, the restriction just becomes
editable from Settings afterwards.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fd2d050e46b2'
down_revision: Union[str, None] = 'f805aa4bd9aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALL_TABS = ['/dashboard', '/work-orders', '/planner', '/kanban', '/employees', '/analytics']


def upgrade() -> None:
    op.create_table('role_tab_visibility',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('visible_tabs', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_tab_visibility')),
    sa.UniqueConstraint('role', name=op.f('uq_role_tab_visibility_role'))
    )

    table = sa.table(
        'role_tab_visibility',
        sa.column('id', sa.UUID()),
        sa.column('role', sa.String()),
        sa.column('visible_tabs', postgresql.ARRAY(sa.String())),
    )
    op.bulk_insert(table, [
        {'id': uuid.uuid4(), 'role': 'Админ', 'visible_tabs': _ALL_TABS},
        {'id': uuid.uuid4(), 'role': 'Управляющий', 'visible_tabs': _ALL_TABS},
        {'id': uuid.uuid4(), 'role': 'Мастер приёмщик', 'visible_tabs': ['/planner']},
        {'id': uuid.uuid4(), 'role': 'Бухгалтер', 'visible_tabs': _ALL_TABS},
        {'id': uuid.uuid4(), 'role': 'Сотрудник', 'visible_tabs': _ALL_TABS},
    ])


def downgrade() -> None:
    op.drop_table('role_tab_visibility')
