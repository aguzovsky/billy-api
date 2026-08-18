"""add photo_url column to establishments

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("photo_url", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("establishments", "photo_url")
