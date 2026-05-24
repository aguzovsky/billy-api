"""create user_consents table

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_consents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("terms_version", sa.String(20), nullable=False),
        sa.Column("privacy_version", sa.String(20), nullable=False),
        sa.Column("image_consent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("model_improvement_consent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])


def downgrade():
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_table("user_consents")
