"""bronze tables

Revision ID: 0001_bronze
Revises:
Create Date: 2026-10-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_bronze"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bronze_crimes_raw",
        sa.Column("raw_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("load_ts", sa.DateTime(timezone=False), nullable=False),
        sa.Column("row_num", sa.Integer(), nullable=False),
        sa.Column("fecha_hecho_raw", sa.Text(), nullable=True),
        sa.Column("cod_depto_raw", sa.Text(), nullable=True),
        sa.Column("departamento_raw", sa.Text(), nullable=True),
        sa.Column("cod_muni_raw", sa.Text(), nullable=True),
        sa.Column("municipio_raw", sa.Text(), nullable=True),
        sa.Column("zona_raw", sa.Text(), nullable=True),
        sa.Column("cantidad_raw", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("raw_id"),
        sa.UniqueConstraint("source_sha256", "row_num", name="uq_bronze_source_row"),
    )
    op.create_index(
        "ix_bronze_crimes_raw_source_sha256",
        "bronze_crimes_raw",
        ["source_sha256"],
    )

    op.create_table(
        "bronze_ingestion_log",
        sa.Column("ingestion_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("ingestion_id"),
    )
    op.create_index(
        "ix_bronze_ingestion_log_source_sha256",
        "bronze_ingestion_log",
        ["source_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_bronze_ingestion_log_source_sha256", table_name="bronze_ingestion_log")
    op.drop_table("bronze_ingestion_log")
    op.drop_index("ix_bronze_crimes_raw_source_sha256", table_name="bronze_crimes_raw")
    op.drop_table("bronze_crimes_raw")
