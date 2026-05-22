"""add pet_photos table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pet_photos",
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
        sa.Column("photo_url", sa.Text(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_pet_photos_pet_id", "pet_photos", ["pet_id"])

    # Migrate existing primary photos from pets.photo_url
    op.execute(
        """
        INSERT INTO pet_photos (id, pet_id, photo_url, is_primary, created_at)
        SELECT gen_random_uuid(), id, photo_url, true, created_at
        FROM pets
        WHERE photo_url IS NOT NULL
        """
    )


def downgrade():
    op.drop_index("ix_pet_photos_pet_id", table_name="pet_photos")
    op.drop_table("pet_photos")
