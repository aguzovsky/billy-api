"""create pro_connect_invites table (BIL-39 — Billy Connect via push)

Ponte real entre pro_pets/pro_clients já cadastrados no Pro e o
usuário/pet correspondente no Billy App. app_user_id/app_pet_id não
têm FK de propósito — cruzam pro schema do App (users/pets), mesmo
padrão já usado em pro_pets.billy_pet_id / pro_clients.billy_user_id.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pro_connect_invites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pro_pet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pro_client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("app_pet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_pro_connect_invites_pro_pet_id", "pro_connect_invites", ["pro_pet_id"])
    op.create_index("idx_pro_connect_invites_app_user_id", "pro_connect_invites", ["app_user_id"])
    op.create_index("idx_pro_connect_invites_status", "pro_connect_invites", ["status"])


def downgrade():
    op.drop_index("idx_pro_connect_invites_status", table_name="pro_connect_invites")
    op.drop_index("idx_pro_connect_invites_app_user_id", table_name="pro_connect_invites")
    op.drop_index("idx_pro_connect_invites_pro_pet_id", table_name="pro_connect_invites")
    op.drop_table("pro_connect_invites")
