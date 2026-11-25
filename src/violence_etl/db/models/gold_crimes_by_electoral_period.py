from sqlalchemy import Column, Integer, Numeric, String

from violence_etl.db.models.base_model import Base


class GoldCrimesByElectoralPeriod(Base):
    __tablename__ = "gold_crimes_by_electoral_period"

    electoral_period = Column(String(20), primary_key=True)
    period_order = Column(Integer, nullable=False)
    year_min = Column(Integer, nullable=False)
    year_max = Column(Integer, nullable=False)
    total_crimes = Column(Integer, nullable=False)
    pct_of_total = Column(Numeric(6, 2), nullable=False)
