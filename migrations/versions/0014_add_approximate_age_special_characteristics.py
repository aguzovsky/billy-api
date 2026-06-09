"""add approximate_age and special_characteristics to pets

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pets", sa.Column("approximate_age", sa.String(), nullable=True))
    op.add_column("pets", sa.Column("special_characteristics", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("pets", "special_characteristics")
    op.drop_column("pets", "approximate_age")
