"""add tags column to establishments

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "establishments",
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("establishments", "tags")
