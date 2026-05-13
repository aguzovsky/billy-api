"""Add reminders and health_logs tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reminders',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pet_id', UUID(as_uuid=True), sa.ForeignKey('pets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recurrence_days', sa.Integer, nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_reminders_user_id', 'reminders', ['user_id'])
    op.create_index('ix_reminders_pet_id', 'reminders', ['pet_id'])
    op.create_index('ix_reminders_due_date', 'reminders', ['due_date'])

    op.create_table('health_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pet_id', UUID(as_uuid=True), sa.ForeignKey('pets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_health_logs_user_id', 'health_logs', ['user_id'])
    op.create_index('ix_health_logs_pet_id', 'health_logs', ['pet_id'])


def downgrade():
    op.drop_index('ix_health_logs_pet_id', 'health_logs')
    op.drop_index('ix_health_logs_user_id', 'health_logs')
    op.drop_table('health_logs')

    op.drop_index('ix_reminders_due_date', 'reminders')
    op.drop_index('ix_reminders_pet_id', 'reminders')
    op.drop_index('ix_reminders_user_id', 'reminders')
    op.drop_table('reminders')
