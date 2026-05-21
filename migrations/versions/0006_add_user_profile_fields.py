"""Add user profile fields: cpf, photo_url, is_verified

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('cpf', sa.String(14), nullable=True))
    op.add_column('users', sa.Column('photo_url', sa.Text(), nullable=True))
    op.add_column('users', sa.Column(
        'is_verified',
        sa.Boolean(),
        nullable=False,
        server_default='false',
    ))
    op.create_unique_constraint('uq_users_cpf', 'users', ['cpf'])


def downgrade():
    op.drop_constraint('uq_users_cpf', 'users', type_='unique')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'photo_url')
    op.drop_column('users', 'cpf')
