from violence_etl.db.models.base_model import Base
from sqlalchemy import Column, Integer, String, PrimaryKeyConstraint

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