from sqlalchemy import Column, BigInteger, String, Text, Integer, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String)           # название
    model_params = Column(Text)     # модель, параметры

    # Связи
    skills = relationship("Skill", back_populates="equipment")
    application_equipment_links = relationship("ApplicationEquipment", back_populates="equipment")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String)           # название
    street_id = Column(BigInteger, ForeignKey("streets.id"))
    house_number = Column(Integer)  # номер дома

    # Связи
    street = relationship("Street", back_populates="warehouses")
    stocks = relationship("WarehouseStock", back_populates="warehouse")


class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String)           # наименование
    description = Column(Text)      # описание
    price = Column(Numeric(10, 2))  # цена (money)

    # Связи
    warehouse_stocks = relationship("WarehouseStock", back_populates="spare_part")


class WarehouseStock(Base):
    __tablename__ = "warehouse_stock"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    warehouse_id = Column(BigInteger, ForeignKey("warehouses.id"))
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"))
    # В таблице на фото нет кол-ва, но по логике оно нужно. Добавил для полноты.
    quantity = Column(Integer, default=0) 

    # Связи
    warehouse = relationship("Warehouse", back_populates="stocks")
    spare_part = relationship("SparePart", back_populates="warehouse_stocks")