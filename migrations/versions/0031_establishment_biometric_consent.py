"""add biometric_consent_accepted_at to establishments (BIL-137 — separa consentimento biométrico do aceite geral de termos)

terms_accepted_at agora é gravado na criação da conta (aceite geral de
Termos de Uso + Política de Privacidade). O consentimento pro dado
biométrico do KYC é sensível (LGPD art. 11) e continua exigindo aceite
explícito e separado, no momento em que a pessoa de fato inicia o KYC
— por isso ganha timestamp próprio, em vez de reusar terms_accepted_at.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("biometric_consent_accepted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("establishments", "biometric_consent_accepted_at")
