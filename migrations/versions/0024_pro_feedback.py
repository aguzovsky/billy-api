"""create pro_feedback table (BIL-103 — avaliação/feedback do Pro)

MVP: sem painel de admin, consulta é direto no banco por enquanto.
Sem coluna de environment de propósito — staging e produção são
bancos fisicamente separados, cada linha só pode existir em um dos
dois, então a coluna seria redundante (diferente de PostHog/Sentry,
onde todo ambiente cai no mesmo projeto compartilhado).

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pro_feedback",
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
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_pro_feedback_establishment_id", "pro_feedback", ["establishment_id"])


def downgrade():
    op.drop_index("idx_pro_feedback_establishment_id", table_name="pro_feedback")
    op.drop_table("pro_feedback")
