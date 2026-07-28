"""add cnpj, cpf, cep columns to establishments (BIL-45)

Migração puramente aditiva, todas nullable — nenhum estabelecimento
existente precisa de backfill. Sem validação de dígito verificador
aqui (isso é KYC de verdade, escopo do BIL-46) — só captura e
persistência do dado, string livre.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("cnpj", sa.String(20), nullable=True))
    op.add_column("establishments", sa.Column("cpf", sa.String(14), nullable=True))
    op.add_column("establishments", sa.Column("cep", sa.String(10), nullable=True))


def downgrade():
    op.drop_column("establishments", "cep")
    op.drop_column("establishments", "cpf")
    op.drop_column("establishments", "cnpj")
