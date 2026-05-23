"""create health_events table

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "health_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("next_date", sa.Date, nullable=True),
        sa.Column("vet_name", sa.String(200), nullable=True),
        sa.Column("clinic", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("proof_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_health_events_pet_id", "health_events", ["pet_id"])
    op.create_index("ix_health_events_date", "health_events", ["date"])
    op.create_index("ix_health_events_next_date", "health_events", ["next_date"])


def downgrade():
    op.drop_index("ix_health_events_next_date", table_name="health_events")
    op.drop_index("ix_health_events_date", table_name="health_events")
    op.drop_index("ix_health_events_pet_id", table_name="health_events")
    op.drop_table("health_events")
