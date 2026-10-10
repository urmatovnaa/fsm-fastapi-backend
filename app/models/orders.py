from sqlalchemy import Column, BigInteger, String, Integer, Text, Numeric, DateTime, Date, Time, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class Status(Base):
    __tablename__ = "statuses"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False)

    requests = relationship("Request", back_populates="status")
    orders = relationship("Order", back_populates="status")

class Street(Base):
    __tablename__ = "streets"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, nullable=False)

    requests = relationship("Request", back_populates="street")
    warehouses = relationship("Warehouse", back_populates="street")

class Request(Base):
    __tablename__ = "requests"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    status_id = Column(BigInteger, ForeignKey("statuses.id"), nullable=True)
    created_at = Column(DateTime, nullable=False) # дата, время создания
    visit_date = Column(Date, nullable=True) # дата от пользователя
    visit_time_start = Column(Time, nullable=True) # время нч приезда
    visit_time_end = Column(Time, nullable=True) 
    
    # Поля адреса (см. корректировку 8)
    street_id = Column(BigInteger, ForeignKey("streets.id"), nullable=True)
    house_number = Column(Integer, nullable=True)
    
    latitude = Column(Integer, nullable=True)
    longitude = Column(Integer, nullable=True)
    problem_description = Column(Text, nullable=True)

    # Связи
    user = relationship("User")
    status = relationship("Status", back_populates="requests")
    street = relationship("Street", back_populates="requests")
    technics = relationship("RequestTechnic", back_populates="request")
    orders = relationship("Order", back_populates="request")


class RequestTechnic(Base):
    __tablename__ = "request_technics"

    request_id = Column(BigInteger, ForeignKey("requests.id"), primary_key=True)
    technic_id = Column(BigInteger, ForeignKey("technics.id"), primary_key=True)

    request = relationship("Request", back_populates="technics")
    technic = relationship("Technic", back_populates="request_technics")

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(BigInteger, primary_key=True, index=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # Корректировка 5: id_заказа необязательное
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=True)

    worker = relationship("Worker", back_populates="schedules")
    order = relationship("Order")

class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, index=True)
    request_id = Column(BigInteger, ForeignKey("requests.id"), nullable=False)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=True)
    brigade_id = Column(BigInteger, ForeignKey("brigades.id"), nullable=True)
    status_id = Column(BigInteger, ForeignKey("statuses.id"), nullable=True)
    priority = Column(Integer, nullable=True)
    
    appointment_time = Column(DateTime, nullable=True)
    work_start_time = Column(DateTime, nullable=True)
    work_end_time = Column(DateTime, nullable=True)
    
    checklist = Column(Text, nullable=True)
    work_description = Column(Text, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True) # сумма
    client_review = Column(Text, nullable=True)
    worker_review = Column(Text, nullable=True)

    # Связи
    request = relationship("Request", back_populates="orders")
    worker = relationship("Worker", back_populates="orders")
    status = relationship("Status", back_populates="orders")
    photos = relationship("OrderPhoto", back_populates="order")
    parts = relationship("OrderPart", back_populates="order")

class OrderPart(Base):
    __tablename__ = "order_parts"

    id = Column(BigInteger, primary_key=True, index=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"), nullable=True)
    quantity = Column(Integer, nullable=False) # кол-во

    order = relationship("Order", back_populates="parts")
    spare_part = relationship("SparePart", back_populates="order_parts")

class OrderPhoto(Base):
    __tablename__ = "order_photos"

    id = Column(BigInteger, primary_key=True, index=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    photo_url = Column(Text, nullable=False) # фото
    photo_type = Column(Boolean, nullable=True) # тип фото (до/после)

    order = relationship("Order", back_populates="photos")