"""cash book (Касса)

Revision ID: e3b9a41c7d52
Revises: c7d4e9f21a08
Create Date: 2026-10-24 00:00:00.000000

Adds the cash book: the cash_entries table, the locked-period settings
(app_settings.cash_lock_from/cash_lock_to) and the per-role "Все
подразделения" flag (role_tab_visibility.all_departments).

It also seeds who may reach the new "/cash" tab, so shipping this is safe:
- Админ, Управляющий, Бухгалтер, Мастер приёмщик get the tab; Админ,
  Управляющий and Бухгалтер also get "Все подразделения" (every cash desk);
- Сотрудник does NOT get the tab.
A role that has no row yet is fail-open (sees every tab), so a missing row is
created with exactly the tabs that role already saw (all of them), plus or
minus "/cash" as above - nobody loses a tab they had.

Existing logins keep their old tab list until they log in again (the tab list
is baked into the session cookie).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e3b9a41c7d52'
down_revision: Union[str, None] = 'c7d4e9f21a08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every tab that existed before this migration (models/role_tab_visibility.py's
# NAV_TAB_KEYS minus "/cash") - what a role with no row used to see.
_TABS_BEFORE = [
    "/cockpit",
    "/dashboard",
    "/work-orders",
    "/planner",
    "/kanban",
    "/employees",
    "/analytics",
    "/telephony",
    "/leads",
    "/budget",
]
_ROLES_WITH_CASH = ["Админ", "Управляющий", "Бухгалтер", "Мастер приёмщик"]
_ROLES_ALL_DEPARTMENTS = ["Админ", "Управляющий", "Бухгалтер"]
_ALL_ROLES = ["Админ", "Управляющий", "Мастер приёмщик", "Бухгалтер", "Сотрудник"]


def upgrade() -> None:
    op.create_table(
        'cash_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workshop_id', sa.UUID(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('work_order_id', sa.UUID(), nullable=True),
        sa.Column('work_order_number', sa.String(length=100), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.Column('created_by_name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by_id', sa.UUID(), nullable=True),
        sa.Column('updated_by_name', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], name=op.f('fk_cash_entries_workshop_id_workshops'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], name=op.f('fk_cash_entries_work_order_id_work_orders'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_cash_entries_created_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name=op.f('fk_cash_entries_updated_by_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cash_entries')),
    )
    op.create_index(
        'ix_cash_entries_workshop_id_entry_date', 'cash_entries', ['workshop_id', 'entry_date']
    )

    op.add_column('app_settings', sa.Column('cash_lock_from', sa.Date(), nullable=True))
    op.add_column('app_settings', sa.Column('cash_lock_to', sa.Date(), nullable=True))

    op.add_column(
        'role_tab_visibility',
        sa.Column('all_departments', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    bind = op.get_bind()
    table = sa.table(
        'role_tab_visibility',
        sa.column('id', sa.UUID()),
        sa.column('role', sa.String()),
        sa.column('visible_tabs', postgresql.ARRAY(sa.String())),
        sa.column('all_departments', sa.Boolean()),
    )
    existing = {row.role for row in bind.execute(sa.select(table.c.role))}

    # 1. roles that already have a row: add "/cash" for those that get it.
    for role in _ROLES_WITH_CASH:
        if role in existing:
            bind.execute(
                sa.text(
                    "UPDATE role_tab_visibility "
                    "SET visible_tabs = array_append(visible_tabs, '/cash') "
                    "WHERE role = :role AND NOT ('/cash' = ANY(visible_tabs))"
                ),
                {"role": role},
            )

    # 2. roles without a row (they saw every tab): create one that keeps that.
    for role in _ALL_ROLES:
        if role in existing:
            continue
        tabs = list(_TABS_BEFORE) + (['/cash'] if role in _ROLES_WITH_CASH else [])
        bind.execute(
            sa.text(
                "INSERT INTO role_tab_visibility (id, role, visible_tabs, all_departments) "
                "VALUES (gen_random_uuid(), :role, :tabs, false)"
            ),
            {"role": role, "tabs": tabs},
        )

    # 3. "Все подразделения" for the roles that manage every workshop.
    for role in _ROLES_ALL_DEPARTMENTS:
        bind.execute(
            sa.text("UPDATE role_tab_visibility SET all_departments = true WHERE role = :role"),
            {"role": role},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE role_tab_visibility SET visible_tabs = array_remove(visible_tabs, '/cash')"
        )
    )
    op.drop_column('role_tab_visibility', 'all_departments')
    op.drop_column('app_settings', 'cash_lock_to')
    op.drop_column('app_settings', 'cash_lock_from')
    op.drop_index('ix_cash_entries_workshop_id_entry_date', table_name='cash_entries')
    op.drop_table('cash_entries')
