"""website leads request meta (с какого сайта пришла заявка)

Revision ID: e7b1d5a9c3f4
Revises: d6a0c4f8b2e3
Create Date: 2026-11-16 18:00:00.000000

website_leads.request_meta - Origin / Referer / IP / User-Agent of the intake request, to tell
which of the sites sent a lead.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e7b1d5a9c3f4'
down_revision: Union[str, None] = 'd6a0c4f8b2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'website_leads', sa.Column('request_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('website_leads', 'request_meta')
