from sqlalchemy import Column, DateTime, Integer, String, Text

from violence_etl.db.models.base_model import Base


class SilverRejectedRows(Base):
    __tablename__ = "silver_rejected_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_sha256 = Column(String(64), nullable=True)
    row_num = Column(Integer, nullable=True)
    reject_reason = Column(String(64), nullable=False)
    raw_values = Column(Text, nullable=False)          # JSON string of raw dict
    rejected_at = Column(DateTime(timezone=False), nullable=False)
