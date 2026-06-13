"""add pet_registrations table, migrate data, drop old id columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pet_registrations",
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
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("type_label", sa.String(100), nullable=True),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("idx_pet_registrations_pet_id", "pet_registrations", ["pet_id"])

    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pets' AND column_name='microchip_id') THEN
            INSERT INTO pet_registrations (pet_id, type, number)
            SELECT id, 'MICROCHIP', microchip_id FROM pets WHERE microchip_id IS NOT NULL;
          END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pets' AND column_name='sinpatinhas_id') THEN
            INSERT INTO pet_registrations (pet_id, type, number)
            SELECT id, 'SINPATINHAS', sinpatinhas_id FROM pets WHERE sinpatinhas_id IS NOT NULL;
          END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pets' AND column_name='rg_animal_id') THEN
            INSERT INTO pet_registrations (pet_id, type, number)
            SELECT id, 'RGA-SP', rg_animal_id FROM pets WHERE rg_animal_id IS NOT NULL;
          END IF;
        END $$
    """)

    op.execute("ALTER TABLE pets DROP COLUMN IF EXISTS microchip_id")
    op.execute("ALTER TABLE pets DROP COLUMN IF EXISTS sinpatinhas_id")
    op.execute("ALTER TABLE pets DROP COLUMN IF EXISTS rg_animal_id")


def downgrade():
    op.add_column("pets", sa.Column("rg_animal_id", sa.String(50), nullable=True))
    op.add_column("pets", sa.Column("sinpatinhas_id", sa.String(50), nullable=True))
    op.add_column("pets", sa.Column("microchip_id", sa.String(50), nullable=True))

    op.execute("UPDATE pets p SET microchip_id = r.number "
               "FROM pet_registrations r WHERE r.pet_id = p.id AND r.type = 'MICROCHIP'")
    op.execute("UPDATE pets p SET sinpatinhas_id = r.number "
               "FROM pet_registrations r WHERE r.pet_id = p.id AND r.type = 'SINPATINHAS'")
    op.execute("UPDATE pets p SET rg_animal_id = r.number "
               "FROM pet_registrations r WHERE r.pet_id = p.id AND r.type = 'RGA-SP'")

    op.drop_index("idx_pet_registrations_pet_id", table_name="pet_registrations")
    op.drop_table("pet_registrations")
