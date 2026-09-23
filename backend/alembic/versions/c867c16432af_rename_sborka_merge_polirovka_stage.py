"""rename Сборка to Сборка-Полировка, merge Полировка into it

Revision ID: c867c16432af
Revises: a60cd9ebd165
Create Date: 2026-09-23 15:00:00.000000

Pure data migration - BODY_STAGE_TYPES itself isn't a DB constraint (see
models/planner_constants.py), only a Pydantic-layer closed set, so existing
"Сборка"/"Полировка" rows need updating here to stay pickable/editable
through the dialog after the rename.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c867c16432af'
down_revision: Union[str, None] = 'a60cd9ebd165'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE body_car_stages SET stage_name = 'Сборка-Полировка' "
        "WHERE stage_name IN ('Сборка', 'Полировка')"
    )


def downgrade() -> None:
    op.execute("UPDATE body_car_stages SET stage_name = 'Сборка' WHERE stage_name = 'Сборка-Полировка'")
