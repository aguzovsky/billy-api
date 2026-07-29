"""add photo_url column to pro_pets (BIL-98)

Mesmo padrão da 0020 (photo_url em establishments, BIL-61) — só que
pra pets do Pro. Achado durante teste do BIL-97: ProPet nunca teve
coluna de foto, upload era "Em breve" no NewClientModal.tsx.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pro_pets", sa.Column("photo_url", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("pro_pets", "photo_url")
