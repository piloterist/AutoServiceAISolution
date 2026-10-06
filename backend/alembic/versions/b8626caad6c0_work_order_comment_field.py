"""work order comment field

Revision ID: b8626caad6c0
Revises: 8efeed094dce
Create Date: 2026-10-06 13:01:41.316273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8626caad6c0'
down_revision: Union[str, None] = '8efeed094dce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "comment")
