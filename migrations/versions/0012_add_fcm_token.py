"""add fcm_token to users

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("fcm_token", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("users", "fcm_token")
