from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, Numeric
from sqlalchemy.orm import relationship
from .base import Base

class Technique(Base):
    __tablename__ = "techniques"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)
    model_parameters = Column(Text, nullable=True)

    requests = relationship("RequestTechnique", back_populates="technique")

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)
    street_id = Column(BigInteger, ForeignKey("streets.id"), nullable=True)
    house_number = Column(Integer, nullable=True)

    street = relationship("Street", back_populates="warehouses")
    inventory_items = relationship("WarehouseInventory", back_populates="warehouse")

class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)
    type = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)

    warehouse_items = relationship("WarehouseInventory", back_populates="spare_part")
    orders = relationship("OrderSparePart", back_populates="spare_part")

class WarehouseInventory(Base):
    __tablename__ = "warehouse_inventory"

    warehouse_id = Column(BigInteger, ForeignKey("warehouses.id"), primary_key=True)
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"), primary_key=True)

    warehouse = relationship("Warehouse", back_populates="inventory_items")
    spare_part = relationship("SparePart", back_populates="warehouse_items")