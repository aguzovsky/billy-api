"""Add pet_guardians table for shared custody

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pet_guardians",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pet_id", UUID(as_uuid=True), sa.ForeignKey("pets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guardian_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invited_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pet_guardians_guardian_id", "pet_guardians", ["guardian_id"])
    op.create_index("ix_pet_guardians_pet_id", "pet_guardians", ["pet_id"])


def downgrade() -> None:
    op.drop_table("pet_guardians")
