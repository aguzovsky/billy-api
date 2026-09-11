"""add app_build_number to users (BIL-162)

Backend precisa saber a build do app que o tutor tem instalada pra
recusar o convite do Billy Connect (BIL-148) quando a versão não sabe
tratar a notificação — hoje o tap fica silenciosamente sem efeito em
builds antigas. Populado pelo Flutter junto do fcm_token em PATCH
/auth/me; nulo pra quem ainda não atualizou pra essa build.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("app_build_number", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("users", "app_build_number")
