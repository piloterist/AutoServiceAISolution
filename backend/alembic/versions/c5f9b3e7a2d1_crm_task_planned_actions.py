"""crm task planned actions (запланированные действия по карточке доски задач)

Revision ID: c5f9b3e7a2d1
Revises: b4e8a2d6f1c9
Create Date: 2026-11-16 10:00:00.000000

crm_tasks.next_action_date - the latest planned contact date (colouring in "На контроле" counts
from it instead of from the move to the column); crm_task_actions - the history of every plan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5f9b3e7a2d1'
down_revision: Union[str, None] = 'b4e8a2d6f1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_tasks', sa.Column('next_action_date', sa.Date(), nullable=True))
    op.create_table(
        'crm_task_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('planned_date', sa.Date(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('author_name', sa.String(length=255), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['task_id'], ['crm_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_crm_task_actions_task_id'), 'crm_task_actions', ['task_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_crm_task_actions_task_id'), table_name='crm_task_actions')
    op.drop_table('crm_task_actions')
    op.drop_column('crm_tasks', 'next_action_date')
