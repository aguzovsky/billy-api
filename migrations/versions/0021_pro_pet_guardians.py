"""create pro_pet_guardians table (BIL-95 — guarda compartilhada no Pro)

Migração puramente aditiva: pro_pets.client_id continua o dono
principal, sem mudança nenhuma nos pets existentes, zero backfill.
Essa tabela só guarda guardiões ADICIONAIS além do dono. Diferente do
pet_guardians do Billy App (fluxo de convite por email, pending/
accepted/declined) — aqui é o profissional que gerencia diretamente,
sem convite, porque quem administra é o próprio estabelecimento, não
o guardião sendo convidado.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pro_pet_guardians",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("pet_id", "client_id", name="uq_pro_pet_guardians_pet_client"),
    )
    op.create_index("idx_pro_pet_guardians_pet_id", "pro_pet_guardians", ["pet_id"])
    op.create_index("idx_pro_pet_guardians_client_id", "pro_pet_guardians", ["client_id"])


def downgrade():
    op.drop_index("idx_pro_pet_guardians_client_id", table_name="pro_pet_guardians")
    op.drop_index("idx_pro_pet_guardians_pet_id", table_name="pro_pet_guardians")
    op.drop_table("pro_pet_guardians")
