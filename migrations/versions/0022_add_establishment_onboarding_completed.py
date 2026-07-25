"""add onboarding_completed column to establishments (BIL-101)

Migração aditiva: NOT NULL com server_default=false, então linhas
existentes não precisam de backfill separado — todo estabelecimento
já cadastrado passa a valer como "ainda não viu o onboarding guiado",
o que é o comportamento certo (eles nunca viram mesmo).

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "establishments",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("establishments", "onboarding_completed")
