from violence_etl.db.models.base_model import Base
from sqlalchemy import Column, Date, Integer, String, UniqueConstraint, Index
from sqlalchemy.types import DateTime


class SilverCrimes(Base):
    __tablename__ = "silver_crimes"
    __table_args__ = (
        UniqueConstraint(
            "fecha_hecho",
            "cod_depto",
            "cod_muni",
            "zona",
            "cantidad",
            name="uq_silver_business_key",
        ),
        Index("ix_silver_year_period", "year", "electoral_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha_hecho = Column(Date, nullable=False, index=True)
    cod_depto = Column(String(2), nullable=False)
    departamento = Column(String(100), nullable=False)
    cod_muni = Column(String(5), nullable=False)
    municipio = Column(String(150), nullable=False)
    zona = Column(String(10), nullable=False)
    cantidad = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    weekday_num = Column(Integer, nullable=False)
    weekday_name = Column(String(10), nullable=False)
    electoral_period = Column(String(20), nullable=False, index=True)
    row_hash = Column(String(64), nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    silver_loaded_at = Column(DateTime(timezone=False), nullable=False)