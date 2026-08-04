"""relax pro_connect_invites for the relationship model (BIL-148)

Convite Billy Connect deixa de ser por pet e passa a ser por relação
tutor↔profissional (pro_client_id já existia e já era NOT NULL —
sempre foi o ponto de ancoragem certo, só nunca foi usado sozinho).
Duas constraints relaxadas, nenhuma coluna removida, nenhum dado
histórico tocado:

- pro_pet_id vira opcional: o convite passa a poder nascer só a
  partir do cliente, mesmo sem nenhum pro_pet cadastrado ainda (pets
  futuros entram na relação sem precisar de novo convite). Quando a
  criação parte de um pet específico (fluxo atual do Pro), o campo
  continua sendo populado — vira só contexto/auditoria, não é mais o
  que decide o que fica conectado.
- expires_at vira opcional: convite deixa de expirar. Linhas antigas
  mantêm o valor que já tinham; convites novos não populam mais esse
  campo.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("pro_connect_invites", "pro_pet_id", nullable=True)
    op.alter_column("pro_connect_invites", "expires_at", nullable=True)


def downgrade():
    op.alter_column("pro_connect_invites", "expires_at", nullable=False)
    op.alter_column("pro_connect_invites", "pro_pet_id", nullable=False)
