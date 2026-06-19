"""align pro_pets/pro_clients schema with billy_app

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    # pro_clients: phone -> contact_phone (mesmo nome do User do Billy App)
    op.alter_column("pro_clients", "phone", new_column_name="contact_phone")

    # pro_pets: novas colunas
    op.add_column("pro_pets", sa.Column("approximate_age", sa.String(10), nullable=True))
    op.add_column("pro_pets", sa.Column("color", sa.String(100), nullable=True))
    op.add_column("pro_pets", sa.Column("gender", sa.String(10), nullable=True, server_default="unknown"))
    op.add_column("pro_pets", sa.Column("special_characteristics", sa.Text(), nullable=True))

    # migra dados: temperament + alerts -> special_characteristics (concatenados)
    op.execute("""
        UPDATE pro_pets
        SET special_characteristics = trim(concat_ws(' | ', temperament, alerts))
        WHERE temperament IS NOT NULL OR alerts IS NOT NULL
    """)

    # migra species: cachorro/gato/outro -> dog/cat (igual ao Billy App; 'outro' vira 'dog' por falta de opção melhor)
    op.execute("""
        UPDATE pro_pets
        SET species = CASE species
            WHEN 'cachorro' THEN 'dog'
            WHEN 'gato' THEN 'cat'
            ELSE 'dog'
        END
    """)

    op.drop_column("pro_pets", "age")
    op.drop_column("pro_pets", "temperament")
    op.drop_column("pro_pets", "alerts")


def downgrade():
    op.add_column("pro_pets", sa.Column("age", sa.String(50), nullable=True))
    op.add_column("pro_pets", sa.Column("temperament", sa.String(255), nullable=True))
    op.add_column("pro_pets", sa.Column("alerts", sa.String(255), nullable=True))

    op.execute("""
        UPDATE pro_pets
        SET species = CASE species
            WHEN 'dog' THEN 'cachorro'
            WHEN 'cat' THEN 'gato'
            ELSE 'outro'
        END
    """)

    op.drop_column("pro_pets", "special_characteristics")
    op.drop_column("pro_pets", "gender")
    op.drop_column("pro_pets", "color")
    op.drop_column("pro_pets", "approximate_age")

    op.alter_column("pro_clients", "contact_phone", new_column_name="phone")
