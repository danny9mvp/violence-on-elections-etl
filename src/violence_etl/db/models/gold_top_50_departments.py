from violence_etl.db.models.base_model import Base
from sqlalchemy import Column, Integer, String, Text, DateTime

class GoldTop5Departments(Base):
    __tablename__ = "gold_top5_departments"

    rank = Column(Integer, primary_key=True)
    cod_depto = Column(String(2), nullable=False)
    departamento = Column(String(100), nullable=False)
    total_crimes = Column(Integer, nullable=False)