"""Add user extended profile: gender, birth_date, city, state, whatsapp

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('gender', sa.String(20), nullable=True))
    op.add_column('users', sa.Column('birth_date', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('state', sa.String(2), nullable=True))
    op.add_column('users', sa.Column('whatsapp', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('users', 'whatsapp')
    op.drop_column('users', 'state')
    op.drop_column('users', 'city')
    op.drop_column('users', 'birth_date')
    op.drop_column('users', 'gender')
