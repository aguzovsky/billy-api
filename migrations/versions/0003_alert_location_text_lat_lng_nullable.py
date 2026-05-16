"""Add location_text to alerts, make lat/lng nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alerts', sa.Column('location_text', sa.Text(), nullable=True))
    op.alter_column('alerts', 'lat', nullable=True)
    op.alter_column('alerts', 'lng', nullable=True)


def downgrade():
    op.drop_column('alerts', 'location_text')
    op.execute("UPDATE alerts SET lat = 0.0 WHERE lat IS NULL")
    op.execute("UPDATE alerts SET lng = 0.0 WHERE lng IS NULL")
    op.alter_column('alerts', 'lat', nullable=False)
    op.alter_column('alerts', 'lng', nullable=False)
