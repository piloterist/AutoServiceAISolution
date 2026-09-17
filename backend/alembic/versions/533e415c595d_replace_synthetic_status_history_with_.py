"""replace synthetic status history with real 1C version history

Revision ID: 533e415c595d
Revises: cc7d74aeaf6f
Create Date: 2026-09-18 09:00:00.000000

Clears out the old snapshot-diff-based status history (built by this app
from consecutive imports, timestamped with this backend's own clock) and
reshapes the table to hold real status-change events sourced from 1C's
own РегистрСведений.пп_ВерсииОбъектов version log instead. See
services/import_service.py and 1c/TestExportOrders.bsl.

The old rows are deleted (not migrated) - they were synthetic
approximations, not real data, and the whole point of this change is that
they get replaced by real history from 1C on the next import. Only this
app's own copy is affected; 1C itself is untouched (this integration is
read-only against 1C throughout).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '533e415c595d'
down_revision: Union[str, None] = 'cc7d74aeaf6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM work_order_status_history")

    op.drop_index(op.f('ix_work_order_status_history_last_seen_at'), table_name='work_order_status_history')
    op.drop_column('work_order_status_history', 'first_seen_at')
    op.drop_column('work_order_status_history', 'last_seen_at')

    op.add_column('work_order_status_history', sa.Column('version_number', sa.Integer(), nullable=False))
    op.add_column('work_order_status_history', sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False))
    op.add_column('work_order_status_history', sa.Column('author', sa.String(length=255), nullable=True))
    op.add_column('work_order_status_history', sa.Column('status_uuid', sa.String(length=36), nullable=True))

    op.create_index(op.f('ix_work_order_status_history_changed_at'), 'work_order_status_history', ['changed_at'], unique=False)
    op.create_unique_constraint('uq_work_order_status_history_version', 'work_order_status_history', ['work_order_id', 'version_number'])


def downgrade() -> None:
    op.execute("DELETE FROM work_order_status_history")

    op.drop_constraint('uq_work_order_status_history_version', 'work_order_status_history', type_='unique')
    op.drop_index(op.f('ix_work_order_status_history_changed_at'), table_name='work_order_status_history')

    op.drop_column('work_order_status_history', 'status_uuid')
    op.drop_column('work_order_status_history', 'author')
    op.drop_column('work_order_status_history', 'changed_at')
    op.drop_column('work_order_status_history', 'version_number')

    op.add_column('work_order_status_history', sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False))
    op.add_column('work_order_status_history', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_work_order_status_history_last_seen_at'), 'work_order_status_history', ['last_seen_at'], unique=False)
