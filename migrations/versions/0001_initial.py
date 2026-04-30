"""Initial schema - all tables

Revision ID: 0001
Revises: 
Create Date: 2026-04-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('contact_phone', sa.String(20), nullable=True),
        sa.Column('neighborhood', sa.String(100), nullable=True),
        sa.Column('reset_token', sa.String(6), nullable=True),
        sa.Column('reset_token_expires', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table('pets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('species', sa.String(10), nullable=False),
        sa.Column('breed', sa.String(100), nullable=True),
        sa.Column('color', sa.String(50), nullable=True),
        sa.Column('gender', sa.String(10), nullable=True),
        sa.Column('owner_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('rg_animal_id', sa.String(50), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='home'),
        sa.Column('photo_url', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table('alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pet_id', UUID(as_uuid=True), sa.ForeignKey('pets.id'), nullable=False),
        sa.Column('alert_type', sa.String(10), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('lat', sa.Float, nullable=True),
        sa.Column('lng', sa.Float, nullable=True),
        sa.Column('radius_km', sa.Float, nullable=True),
        sa.Column('photo_url', sa.String(500), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('pet_guardians',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pet_id', UUID(as_uuid=True), sa.ForeignKey('pets.id'), nullable=False),
        sa.Column('guardian_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('invited_by_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table('biometrics',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pet_id', UUID(as_uuid=True), sa.ForeignKey('pets.id'), nullable=False),
        sa.Column('embedding', Vector(2048), nullable=False),
        sa.Column('quality_score', sa.Float, nullable=True),
        sa.Column('capture_metadata', JSONB, nullable=True),
        sa.Column('registered_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('biometrics')
    op.drop_table('pet_guardians')
    op.drop_table('alerts')
    op.drop_table('pets')
    op.drop_table('users')
