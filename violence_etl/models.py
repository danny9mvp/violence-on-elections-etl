"""SQLAlchemy models for every layer.

Table-name prefixes (``bronze_``, ``silver_``, ``gold_``) are used instead of
PostgreSQL schemas because SQLite has no schemas. One model set therefore
renders identically on SQLite (staging/tests) and PostgreSQL (warehouse).

Classic ``Column(...)`` declarative style is used on purpose (no ``Mapped[...]``)
so runtime annotation evaluation stays identical on Python 3.8 and 3.14.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


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


class BronzeIngestionLog(Base):
    __tablename__ = "bronze_ingestion_log"

    ingestion_id = Column(Integer, primary_key=True, autoincrement=True)
    source_url = Column(String(512), nullable=False)
    source_file = Column(String(255), nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    row_count = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)         # "loaded" | "skipped" | "failed"
    message = Column(Text, nullable=True)
    loaded_at = Column(DateTime(timezone=False), nullable=False)


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


class SilverRejectedRows(Base):
    __tablename__ = "silver_rejected_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_sha256 = Column(String(64), nullable=True)
    row_num = Column(Integer, nullable=True)
    reject_reason = Column(String(64), nullable=False)
    raw_values = Column(Text, nullable=False)          # JSON string of raw dict
    rejected_at = Column(DateTime(timezone=False), nullable=False)


class GoldTop5Departments(Base):
    __tablename__ = "gold_top5_departments"

    rank = Column(Integer, primary_key=True)
    cod_depto = Column(String(2), nullable=False)
    departamento = Column(String(100), nullable=False)
    total_crimes = Column(Integer, nullable=False)


class GoldCrimesByDepartment(Base):
    __tablename__ = "gold_crimes_by_department"

    cod_depto = Column(String(2), primary_key=True)
    departamento = Column(String(100), nullable=False)
    total_crimes = Column(Integer, nullable=False)


class GoldCrimesByCalendar(Base):
    __tablename__ = "gold_crimes_by_calendar"
    __table_args__ = (
        PrimaryKeyConstraint("year", "quarter", "month", "weekday_num"),
    )

    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    weekday_num = Column(Integer, nullable=False)
    weekday_name = Column(String(10), nullable=False)
    total_crimes = Column(Integer, nullable=False)


class GoldCrimesByElectoralPeriod(Base):
    __tablename__ = "gold_crimes_by_electoral_period"

    electoral_period = Column(String(20), primary_key=True)
    period_order = Column(Integer, nullable=False)
    year_min = Column(Integer, nullable=False)
    year_max = Column(Integer, nullable=False)
    total_crimes = Column(Integer, nullable=False)
    pct_of_total = Column(Numeric(6, 2), nullable=False)
