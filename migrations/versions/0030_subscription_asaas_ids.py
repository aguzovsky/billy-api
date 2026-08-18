"""add asaas billing fields to establishments (BIL-112)

Migração puramente aditiva, todas nullable exceto payment_status (default
'trial', mesmo estado inicial que ProSubscription.status já usa hoje).
payment_status é varchar solto, não enum de banco — o ciclo de vida ainda
vai ganhar estados novos (cancelamento, troca de plano) e não vale uma
migration a cada um. payment_overdue_since é o âncora dos 7 dias de
carência antes de rebaixar pro plano grátis do track.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishments", sa.Column("asaas_customer_id", sa.String(32), nullable=True))
    op.add_column("establishments", sa.Column("asaas_subscription_id", sa.String(32), nullable=True))
    op.add_column("establishments", sa.Column("payment_status", sa.String(20), nullable=False, server_default="trial"))
    op.add_column("establishments", sa.Column("payment_overdue_since", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("establishments", "payment_overdue_since")
    op.drop_column("establishments", "payment_status")
    op.drop_column("establishments", "asaas_subscription_id")
    op.drop_column("establishments", "asaas_customer_id")
