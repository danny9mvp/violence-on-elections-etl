"""one bronze ingestion log row per source hash

Revision ID: 0004_bronze_ingestion_unique
Revises: 0003_gold
Create Date: 2026-10-13
"""
from __future__ import annotations

from alembic import op

revision = "0004_bronze_ingestion_unique"
down_revision = "0003_gold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Collapse any legacy duplicates, keeping the most recent attempt per hash.
    op.execute(
        "DELETE FROM bronze_ingestion_log WHERE ingestion_id NOT IN ("
        "SELECT keep_id FROM ("
        "SELECT MAX(ingestion_id) AS keep_id FROM bronze_ingestion_log "
        "GROUP BY source_sha256"
        ") AS latest)"
    )
    with op.batch_alter_table("bronze_ingestion_log") as batch_op:
        batch_op.create_unique_constraint(
            "uq_bronze_ingestion_sha", ["source_sha256"]
        )


def downgrade() -> None:
    with op.batch_alter_table("bronze_ingestion_log") as batch_op:
        batch_op.drop_constraint("uq_bronze_ingestion_sha", type_="unique")
