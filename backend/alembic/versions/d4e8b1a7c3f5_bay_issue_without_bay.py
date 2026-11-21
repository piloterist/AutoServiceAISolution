"""bay_issues.bay_id необязателен: ошибка «нет данных из 1С» не относится к боксу

Revision ID: d4e8b1a7c3f5
Revises: c7d2a9e4f1b8
Create Date: 2026-11-21 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e8b1a7c3f5'
down_revision: Union[str, None] = 'c7d2a9e4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('bay_issues', 'bay_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM bay_issues WHERE bay_id IS NULL")
    op.alter_column('bay_issues', 'bay_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)
