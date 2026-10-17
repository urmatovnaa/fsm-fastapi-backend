from sqlalchemy import Column, BigInteger, String, Integer, Text, Numeric, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class Technic(Base):
    __tablename__ = "technics"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False) # название
    # Корректировка 1: модель и параметры могут быть null
    model_params = Column(Text, nullable=True) 

    # Связи
    skills = relationship("Skill", back_populates="technic")
    request_technics = relationship("RequestTechnic", back_populates="technic")

class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False) # наименование
    # Корректировка 4: описание необязательное
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True) # money

    # Связи
    warehouse_stocks = relationship("WarehouseStock", back_populates="spare_part")
    order_parts = relationship("OrderPart", back_populates="spare_part")

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False)
    street_id = Column(BigInteger, ForeignKey("streets.id"), nullable=True)
    house_number = Column(Integer, nullable=True)

    stocks = relationship("WarehouseStock", back_populates="warehouse")
    street = relationship("Street")

class WarehouseStock(Base):
    __tablename__ = "warehouse_stocks"

    id = Column(BigInteger, primary_key=True, index=True)
    warehouse_id = Column(BigInteger, ForeignKey("warehouses.id"), nullable=False)
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"), nullable=False)
    quantity = Column(Integer, nullable=False) # кол-во

    warehouse = relationship("Warehouse", back_populates="stocks")
    spare_part = relationship("SparePart", back_populates="warehouse_stocks")