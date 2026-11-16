from violence_etl.db.models.base_model import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint


class BronzeCrimesRaw(Base):
    __tablename__ = "bronze_crimes_raw"
    __table_args__ = (
        UniqueConstraint("source_sha256", "row_num", name="uq_bronze_source_row"),
    )

    raw_id = Column(Integer, primary_key=True, autoincrement=True)
    source_sha256 = Column(String(64), nullable=False, index=True)
    source_file = Column(String(255), nullable=False)
    source_url = Column(String(512), nullable=False)
    load_ts = Column(DateTime(timezone=False), nullable=False)
    row_num = Column(Integer, nullable=False)          # 1-based data row order
    fecha_hecho_raw = Column(Text, nullable=True)       # verbatim "FECHA HECHO"
    cod_depto_raw = Column(Text, nullable=True)
    departamento_raw = Column(Text, nullable=True)
    cod_muni_raw = Column(Text, nullable=True)
    municipio_raw = Column(Text, nullable=True)
    zona_raw = Column(Text, nullable=True)
    cantidad_raw = Column(Text, nullable=True)