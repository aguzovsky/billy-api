"""add sinpatinhas_id, microchip_id to pets + pet_found_contacts table

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pets", sa.Column("sinpatinhas_id", sa.String(50), nullable=True))
    op.add_column("pets", sa.Column("microchip_id", sa.String(50), nullable=True))

    op.create_table(
        "pet_found_contacts",
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
        sa.Column("finder_name", sa.String(100), nullable=False),
        sa.Column("finder_phone", sa.String(20), nullable=False),
        sa.Column("location_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_pet_found_contacts_pet_id", "pet_found_contacts", ["pet_id"])


def downgrade():
    op.drop_index("ix_pet_found_contacts_pet_id", table_name="pet_found_contacts")
    op.drop_table("pet_found_contacts")
    op.drop_column("pets", "microchip_id")
    op.drop_column("pets", "sinpatinhas_id")
