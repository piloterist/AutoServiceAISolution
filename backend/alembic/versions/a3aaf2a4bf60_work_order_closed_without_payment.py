"""work order closed without payment field

Revision ID: a3aaf2a4bf60
Revises: e5f95fa648a4
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3aaf2a4bf60'
down_revision: Union[str, None] = 'e5f95fa648a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "closed_without_payment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("work_orders", "closed_without_payment")
