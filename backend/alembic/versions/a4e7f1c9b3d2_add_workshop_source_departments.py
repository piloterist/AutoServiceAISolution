"""add workshop_source_departments

Revision ID: a4e7f1c9b3d2
Revises: f2a6c8e1d4b7
Create Date: 2026-09-28 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4e7f1c9b3d2'
down_revision: Union[str, None] = 'f2a6c8e1d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workshop_source_departments',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('workshop_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('source_department', sa.String(length=150), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workshop_id'], ['workshops.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workshop_source_departments')),
    sa.UniqueConstraint('source_department', name='uq_workshop_source_departments_source_department')
    )
    op.create_index(op.f('ix_workshop_source_departments_workshop_id'), 'workshop_source_departments', ['workshop_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workshop_source_departments_workshop_id'), table_name='workshop_source_departments')
    op.drop_table('workshop_source_departments')
