from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from violence_etl.db.models.base_model import Base


class BronzeIngestionLog(Base):
    __tablename__ = "bronze_ingestion_log"
    # One row per source content hash: repeated attempts (skip or --force)
    # update that row instead of appending, so re-runs are idempotent.
    __table_args__ = (
        UniqueConstraint("source_sha256", name="uq_bronze_ingestion_sha"),
    )

    ingestion_id = Column(Integer, primary_key=True, autoincrement=True)
    source_url = Column(String(512), nullable=False)
    source_file = Column(String(255), nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    row_count = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)         # "loaded" | "skipped" | "failed"
    message = Column(Text, nullable=True)
    loaded_at = Column(DateTime(timezone=False), nullable=False)
