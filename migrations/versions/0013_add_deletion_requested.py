"""add deletion_requested to users

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("deletion_requested", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("users", "deletion_requested_at")
    op.drop_column("users", "deletion_requested")
