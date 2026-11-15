"""crm task comments (комментарии к карточкам доски задач)

Revision ID: f5b2d8e1a7c3
Revises: e4a1c7d3b9f2
Create Date: 2026-11-15 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f5b2d8e1a7c3'
down_revision: Union[str, None] = 'e4a1c7d3b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crm_task_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('author_name', sa.String(length=255), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['task_id'], ['crm_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_crm_task_comments_task_id'), 'crm_task_comments', ['task_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_crm_task_comments_task_id'), table_name='crm_task_comments')
    op.drop_table('crm_task_comments')
