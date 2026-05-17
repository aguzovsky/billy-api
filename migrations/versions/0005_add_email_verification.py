"""Add email verification fields to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='true' so existing users are not blocked
    op.add_column('users', sa.Column(
        'email_verified',
        sa.Boolean(),
        nullable=False,
        server_default='true',
    ))
    op.add_column('users', sa.Column(
        'email_verified_at',
        sa.DateTime(timezone=True),
        nullable=True,
    ))
    op.add_column('users', sa.Column(
        'email_verification_token',
        sa.String(64),
        nullable=True,
    ))
    op.add_column('users', sa.Column(
        'email_verification_token_expires',
        sa.DateTime(timezone=True),
        nullable=True,
    ))


def downgrade():
    op.drop_column('users', 'email_verification_token_expires')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified_at')
    op.drop_column('users', 'email_verified')
