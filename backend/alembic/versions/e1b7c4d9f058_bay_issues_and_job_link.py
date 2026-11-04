"""bay_issues + bay_occupancy.workshop_job_id: video control tied to the planner

Revision ID: e1b7c4d9f058
Revises: d0a6b3c8e947
Create Date: 2026-11-05 10:00:00.000000

A bay entry moves the matching planner record to "В работе" (or creates one); the link is kept
on the occupancy interval so the record can be extended while the car is in the bay and set to
"Готова" after the exit. bay_issues is the "Ошибки" list: a car in a bay without a work order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1b7c4d9f058'
down_revision: Union[str, None] = 'd0a6b3c8e947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bay_occupancy',
        sa.Column('workshop_job_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_bay_occupancy_workshop_job',
        'bay_occupancy',
        'workshop_jobs',
        ['workshop_job_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_table(
        'bay_issues',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bay_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('occupancy_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entry_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('plate', sa.String(length=20), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.String(length=10), nullable=True),
        sa.Column('resolved_by', sa.String(length=255), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['bay_id'], ['bays.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['occupancy_id'], ['bay_occupancy.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entry_event_id'], ['bay_events.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bay_issues_bay_id', 'bay_issues', ['bay_id'])


def downgrade() -> None:
    op.drop_index('ix_bay_issues_bay_id', table_name='bay_issues')
    op.drop_table('bay_issues')
    op.drop_constraint('fk_bay_occupancy_workshop_job', 'bay_occupancy', type_='foreignkey')
    op.drop_column('bay_occupancy', 'workshop_job_id')
