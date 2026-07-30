"""add terms_accepted_at, terms_version to establishments (BIL-46 — LGPD)

Migração puramente aditiva, ambas nullable — nenhuma conta existente
aceitou termos ainda (o próprio motivo desta migration é que os termos
não existiam até agora). Campo permanente: LGPD exige poder provar
quando e o quê foi aceito, não é só um flag booleano.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("establishments", sa.Column("terms_version", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("establishments", "terms_version")
    op.drop_column("establishments", "terms_accepted_at")
