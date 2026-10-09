from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, Numeric, TIMESTAMP, Boolean, Interval
from sqlalchemy.orm import relationship
from .base import Base


class Status(Base):
    __tablename__ = "statuses"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)
    
    requests = relationship("Request", back_populates="status")

class Street(Base):
    __tablename__ = "streets"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)

    requests = relationship("Request", back_populates="street")
    warehouses = relationship("Warehouse", back_populates="street")

class Operation(Base):
    __tablename__ = "operations"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=True)

    skills = relationship("Skill", back_populates="operation")
    requests = relationship("RequestOperation", back_populates="operation")

# --- Main Entities ---

class Request(Base):
    __tablename__ = "requests"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    status_id = Column(BigInteger, ForeignKey("statuses.id"), nullable=True)
    created_at = Column(TIMESTAMP, nullable=True)
    arrival_at = Column(TIMESTAMP, nullable=True)
    street_id = Column(BigInteger, ForeignKey("streets.id"), nullable=True)
    house_number = Column(Integer, nullable=True)
    longitude = Column(Integer, nullable=True)
    latitude = Column(Integer, nullable=True)
    urgency_level = Column(Integer, nullable=True)
    problem_description = Column(Text, nullable=True)
    estimated_execution_time = Column(Interval, nullable=True)
    estimated_price = Column(Numeric(10, 2), nullable=True)

    user = relationship("User", back_populates="requests")
    status = relationship("Status", back_populates="requests")
    street = relationship("Street", back_populates="requests")
    techniques = relationship("RequestTechnique", back_populates="request")
    operations = relationship("RequestOperation", back_populates="request")
    order = relationship("Order", back_populates="request", uselist=False)

class RequestTechnique(Base):
    __tablename__ = "request_techniques"

    request_id = Column(BigInteger, ForeignKey("requests.id"), primary_key=True)
    technique_id = Column(BigInteger, ForeignKey("techniques.id"), primary_key=True)

    request = relationship("Request", back_populates="techniques")
    technique = relationship("Technique", back_populates="requests")

class RequestOperation(Base):
    __tablename__ = "request_operations"

    request_id = Column(BigInteger, ForeignKey("requests.id"), primary_key=True)
    operation_id = Column(BigInteger, ForeignKey("operations.id"), primary_key=True)

    request = relationship("Request", back_populates="operations")
    operation = relationship("Operation", back_populates="requests")

class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    request_id = Column(BigInteger, ForeignKey("requests.id"), nullable=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=True)
    appointment_time = Column(TIMESTAMP, nullable=True)
    work_start_time = Column(TIMESTAMP, nullable=True)
    work_end_time = Column(TIMESTAMP, nullable=True)
    checklist = Column(Integer, nullable=True)
    work_description = Column(Text, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)
    client_review = Column(Text, nullable=True)
    worker_review = Column(Text, nullable=True)

    request = relationship("Request", back_populates="order")
    worker = relationship("Worker", back_populates="orders")
    photos = relationship("OrderPhoto", back_populates="order")
    spare_parts = relationship("OrderSparePart", back_populates="order")

class OrderPhoto(Base):
    __tablename__ = "order_photos"

    order_id = Column(BigInteger, ForeignKey("orders.id"), primary_key=True)
    photo = Column(Text, nullable=True)
    photo_type = Column(Boolean, nullable=True) # e.g., True = after, False = before

    order = relationship("Order", back_populates="photos")

class OrderSparePart(Base):
    __tablename__ = "order_spare_parts"

    order_id = Column(BigInteger, ForeignKey("orders.id"), primary_key=True)
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"), primary_key=True)
    quantity = Column(Integer, nullable=True)

    order = relationship("Order", back_populates="spare_parts")
    spare_part = relationship("SparePart", back_populates="orders")