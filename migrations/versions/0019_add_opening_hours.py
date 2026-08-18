"""add opening_hours column to establishments

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("opening_hours", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("establishments", "opening_hours")
