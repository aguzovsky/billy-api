"""create billy pro tables

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "establishments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("whatsapp", sa.String(20), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("neighborhood", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_email_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "pro_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("billing_cycle", sa.String(10), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_founder", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "pro_clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("document", sa.String(20), nullable=True),
        sa.Column("neighborhood", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("billy_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("billy_profile_status", sa.String(20), nullable=False, server_default="nao_conectado"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_clients_establishment_id", "pro_clients", ["establishment_id"])
    op.create_index("idx_pro_clients_billy_user_id", "pro_clients", ["billy_user_id"])

    op.create_table(
        "pro_pets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "client_id",
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
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("species", sa.String(10), nullable=False),
        sa.Column("breed", sa.String(100), nullable=True),
        sa.Column("age", sa.String(50), nullable=True),
        sa.Column("weight", sa.String(20), nullable=True),
        sa.Column("temperament", sa.String(255), nullable=True),
        sa.Column("alerts", sa.String(255), nullable=True),
        sa.Column("billy_pet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("biometry_status", sa.String(20), nullable=False, server_default="nao_registrada"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_pets_establishment_id", "pro_pets", ["establishment_id"])
    op.create_index("idx_pro_pets_billy_pet_id", "pro_pets", ["billy_pet_id"])

    op.create_table(
        "pro_appointments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service_name", sa.String(100), nullable=False),
        sa.Column("service_price", sa.Float, nullable=True),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("time", sa.String(5), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payment_status", sa.String(20), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=True),
        sa.Column("amount", sa.Float, nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="pro"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_appointments_establishment_id", "pro_appointments", ["establishment_id"])
    op.create_index("idx_pro_appointments_date", "pro_appointments", ["date"])

    op.create_table(
        "pro_services",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("duration", sa.Integer, nullable=True),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_services_establishment_id", "pro_services", ["establishment_id"])

    op.create_table(
        "pro_reminders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "establishment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "pet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pro_pets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("scheduled_date", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_reminders_establishment_id", "pro_reminders", ["establishment_id"])


def downgrade():
    op.drop_index("idx_pro_reminders_establishment_id", table_name="pro_reminders")
    op.drop_table("pro_reminders")

    op.drop_index("idx_pro_services_establishment_id", table_name="pro_services")
    op.drop_table("pro_services")

    op.drop_index("idx_pro_appointments_date", table_name="pro_appointments")
    op.drop_index("idx_pro_appointments_establishment_id", table_name="pro_appointments")
    op.drop_table("pro_appointments")

    op.drop_index("idx_pro_pets_billy_pet_id", table_name="pro_pets")
    op.drop_index("idx_pro_pets_establishment_id", table_name="pro_pets")
    op.drop_table("pro_pets")

    op.drop_index("idx_pro_clients_billy_user_id", table_name="pro_clients")
    op.drop_index("idx_pro_clients_establishment_id", table_name="pro_clients")
    op.drop_table("pro_clients")

    op.drop_table("pro_subscriptions")

    op.drop_table("establishments")
