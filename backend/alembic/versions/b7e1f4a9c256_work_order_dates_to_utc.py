"""work order dates: Moscow wall clock -> real UTC instants

Revision ID: b7e1f4a9c256
Revises: a5c8d2e7f391
Create Date: 2026-10-25 00:00:00.000000

The import used to store work_orders.document_date / created_date /
start_date / end_date / closed_date exactly as 1C sent them - a naive Moscow
wall-clock value that Postgres took as UTC - so every one of them read 3 hours
late (an order closed 22:06 MSK was stored as 22:06 UTC and shown as 01:06 the
next day; status history, payments and calls were already converted). The
import now converts them; this brings the rows already in the table to the
same scale by subtracting those 3 hours (NULLs stay NULL).

Run it exactly once, together with the code that converts on import.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e1f4a9c256'
down_revision: Union[str, None] = 'a5c8d2e7f391'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ['document_date', 'created_date', 'start_date', 'end_date', 'closed_date']


def upgrade() -> None:
    sets = ', '.join(f"{c} = {c} - interval '3 hours'" for c in _COLUMNS)
    op.execute(f'UPDATE work_orders SET {sets}')


def downgrade() -> None:
    sets = ', '.join(f"{c} = {c} + interval '3 hours'" for c in _COLUMNS)
    op.execute(f'UPDATE work_orders SET {sets}')
