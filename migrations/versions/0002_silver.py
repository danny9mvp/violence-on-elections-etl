"""silver tables

Revision ID: 0002_silver
Revises: 0001_bronze
Create Date: 2026-10-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_silver"
down_revision = "0001_bronze"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "silver_crimes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fecha_hecho", sa.Date(), nullable=False),
        sa.Column("cod_depto", sa.String(length=2), nullable=False),
        sa.Column("departamento", sa.String(length=100), nullable=False),
        sa.Column("cod_muni", sa.String(length=5), nullable=False),
        sa.Column("municipio", sa.String(length=150), nullable=False),
        sa.Column("zona", sa.String(length=10), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("weekday_num", sa.Integer(), nullable=False),
        sa.Column("weekday_name", sa.String(length=10), nullable=False),
        sa.Column("electoral_period", sa.String(length=20), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("silver_loaded_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fecha_hecho",
            "cod_depto",
            "cod_muni",
            "zona",
            "cantidad",
            name="uq_silver_business_key",
        ),
    )
    op.create_index("ix_silver_crimes_fecha_hecho", "silver_crimes", ["fecha_hecho"])
    op.create_index("ix_silver_crimes_electoral_period", "silver_crimes", ["electoral_period"])
    op.create_index("ix_silver_crimes_source_sha256", "silver_crimes", ["source_sha256"])
    op.create_index("ix_silver_year_period", "silver_crimes", ["year", "electoral_period"])

    op.create_table(
        "silver_rejected_rows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("row_num", sa.Integer(), nullable=True),
        sa.Column("reject_reason", sa.String(length=64), nullable=False),
        sa.Column("raw_values", sa.Text(), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("silver_rejected_rows")
    op.drop_index("ix_silver_year_period", table_name="silver_crimes")
    op.drop_index("ix_silver_crimes_source_sha256", table_name="silver_crimes")
    op.drop_index("ix_silver_crimes_electoral_period", table_name="silver_crimes")
    op.drop_index("ix_silver_crimes_fecha_hecho", table_name="silver_crimes")
    op.drop_table("silver_crimes")
