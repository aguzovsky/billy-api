"""add email verification code fields to establishments (BIL-44)

Migração puramente aditiva, todas nullable. Padrão de código de 6
dígitos (não link como o Billy App usa em User — ver auth.py) porque
roda dentro do próprio fluxo de completar perfil, sem sair pro e-mail.
email_verification_sent_at existe só pro cooldown de reenvio (60s),
não tem função de auditoria/prova como terms_accepted_at.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("email_verification_code", sa.String(6), nullable=True))
    op.add_column("establishments", sa.Column("email_verification_code_expires", sa.DateTime(timezone=True), nullable=True))
    op.add_column("establishments", sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("establishments", "email_verification_sent_at")
    op.drop_column("establishments", "email_verification_code_expires")
    op.drop_column("establishments", "email_verification_code")
