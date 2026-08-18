"""add onboarding_wizard_completed_at to establishments (BIL-147)

Campo dedicado pro gate do wizard de onboarding (BIL-16), separado de
onboarding_completed (BIL-101, tour guiado — continua com o
comportamento de sempre, sem mudança). Evita reusar o mesmo campo pra
dois sinais que nem sempre coincidem no tempo (plano pago escolhido
durante o onboarding sai da SPA antes da tour guiada rodar).

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("onboarding_wizard_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("establishments", "onboarding_wizard_completed_at")
