"""Initial schema: users, pets, biometrics, alerts with pgvector + PostGIS

Revision ID: 0001
Revises:
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIMS = 2048


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("neighborhood", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "pets",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("species", sa.String(10), nullable=False),
        sa.Column("breed", sa.String(100)),
        sa.Column("owner_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rg_animal_id", sa.String(50)),
        sa.Column("status", sa.String(20), server_default="home"),
        sa.Column("photo_url", sa.Text()),
        sa.Column("lat", sa.Float()),
        sa.Column("lng", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "biometrics",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pet_id", sa.UUID(), sa.ForeignKey("pets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMS), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("capture_metadata", sa.JSON()),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pet_id", sa.UUID(), sa.ForeignKey("pets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("radius_km", sa.Integer(), server_default="10"),
        sa.Column("photo_url", sa.Text()),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )

    # Indexes
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_pets_owner_id", "pets", ["owner_id"])
    op.create_index("ix_pets_status", "pets", ["status"])
    op.create_index("ix_biometrics_pet_id", "biometrics", ["pet_id"])
    op.create_index("ix_alerts_status", "alerts", ["status"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("biometrics")
    op.drop_table("pets")
    op.drop_table("users")
