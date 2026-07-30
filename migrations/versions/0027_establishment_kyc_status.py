"""add kyc_status, kyc_session_id to establishments (BIL-46 — Didit KYC)

Migração puramente aditiva. kyc_status default 'nao_iniciado' pra toda
conta existente (nenhuma tinha KYC, então nenhuma deveria aparecer como
aprovada). kyc_session_id guarda o session_id do Didit — usado pro
webhook e pro fluxo de "tentar novamente" (não é vendor_data; esse é
o próprio establishment_id, enviado na criação da sessão).

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "establishments",
        sa.Column("kyc_status", sa.String(20), nullable=False, server_default="nao_iniciado"),
    )
    op.add_column("establishments", sa.Column("kyc_session_id", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("establishments", "kyc_session_id")
    op.drop_column("establishments", "kyc_status")
