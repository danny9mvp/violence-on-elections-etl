from sqlalchemy import Column, Integer, String

from violence_etl.db.models.base_model import Base


class GoldCrimesByDepartment(Base):
    __tablename__ = "gold_crimes_by_department"

    cod_depto = Column(String(2), primary_key=True)
    departamento = Column(String(100), nullable=False)
    total_crimes = Column(Integer, nullable=False)
