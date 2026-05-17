"""Add source column to pets

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'pets',
        sa.Column(
            'source',
            sa.String(30),
            nullable=False,
            server_default='owner_registered',
        ),
    )


def downgrade():
    op.drop_column('pets', 'source')
