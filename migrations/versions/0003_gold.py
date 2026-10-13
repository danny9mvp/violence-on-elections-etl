"""gold tables

Revision ID: 0003_gold
Revises: 0002_silver
Create Date: 2026-10-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_gold"
down_revision = "0002_silver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gold_top5_departments",
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("cod_depto", sa.String(length=2), nullable=False),
        sa.Column("departamento", sa.String(length=100), nullable=False),
        sa.Column("total_crimes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("rank"),
    )

    op.create_table(
        "gold_crimes_by_department",
        sa.Column("cod_depto", sa.String(length=2), nullable=False),
        sa.Column("departamento", sa.String(length=100), nullable=False),
        sa.Column("total_crimes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("cod_depto"),
    )

    op.create_table(
        "gold_crimes_by_calendar",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("weekday_num", sa.Integer(), nullable=False),
        sa.Column("weekday_name", sa.String(length=10), nullable=False),
        sa.Column("total_crimes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year", "quarter", "month", "weekday_num"),
    )

    op.create_table(
        "gold_crimes_by_electoral_period",
        sa.Column("electoral_period", sa.String(length=20), nullable=False),
        sa.Column("period_order", sa.Integer(), nullable=False),
        sa.Column("year_min", sa.Integer(), nullable=False),
        sa.Column("year_max", sa.Integer(), nullable=False),
        sa.Column("total_crimes", sa.Integer(), nullable=False),
        sa.Column("pct_of_total", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("electoral_period"),
    )


def downgrade() -> None:
    op.drop_table("gold_crimes_by_electoral_period")
    op.drop_table("gold_crimes_by_calendar")
    op.drop_table("gold_crimes_by_department")
    op.drop_table("gold_top5_departments")
