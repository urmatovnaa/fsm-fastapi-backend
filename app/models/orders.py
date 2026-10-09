from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, Boolean, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Status(Base):
    __tablename__ = "statuses"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String)  # название

    # Связи
    applications = relationship("Application", back_populates="status")


class Street(Base):
    __tablename__ = "streets"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String)  # название

    # Связи
    applications = relationship("Application", back_populates="street")
    warehouses = relationship("Warehouse", back_populates="street")


class Application(Base):
    __tablename__ = "applications"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    status_id = Column(BigInteger, ForeignKey("statuses.id"))
    created_at = Column(DateTime)               # дата, время создания
    arrival_time = Column(DateTime, nullable=True) # дата, время приезда от пользователя
    street_id = Column(BigInteger, ForeignKey("streets.id"))
    house_number = Column(Integer)              # номер дома
    longitude = Column(Integer)                 # долгота
    latitude = Column(Integer)                  # широта
    urgency_level = Column(Integer)             # уровень срочности
    problem_description = Column(Text)          # описание проблемы
    estimated_completion_time = Column(DateTime, nullable=True) # приближенное время выполнения
    estimated_price = Column(Numeric(10, 2), nullable=True)     # приближенная цена

    # Связи
    user = relationship("User", back_populates="applications")
    status = relationship("Status", back_populates="applications")
    street = relationship("Street", back_populates="applications")
    equipment_list = relationship("ApplicationEquipment", back_populates="application")
    order = relationship("Order", back_populates="application", uselist=False)


class ApplicationEquipment(Base):
    """Связующая таблица: список техники на заявку"""
    __tablename__ = "application_equipment"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    application_id = Column(BigInteger, ForeignKey("applications.id"))
    equipment_id = Column(BigInteger, ForeignKey("equipment.id"))

    # Связи
    application = relationship("Application", back_populates="equipment_list")
    equipment = relationship("Equipment", back_populates="application_equipment_links")


class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    application_id = Column(BigInteger, ForeignKey("applications.id"))
    worker_id = Column(BigInteger, ForeignKey("workers.id"))
    appointment_time = Column(DateTime, nullable=True) # время назначения
    start_time = Column(DateTime, nullable=True)       # время нч работы
    end_time = Column(DateTime, nullable=True)         # время кц работы
    checklist = Column(Text, nullable=True)            # чек-лист
    work_description = Column(Text, nullable=True)     # описание выполненной работы
    total_amount = Column(Numeric(10, 2), nullable=True) # сумма
    client_review = Column(Text, nullable=True)        # отзыв клиента
    worker_review = Column(Text, nullable=True)        # отзыв работника

    # Связи
    application = relationship("Application", back_populates="order")
    worker = relationship("Worker", back_populates="orders")
    spare_parts_list = relationship("OrderSparePart", back_populates="order")
    photos = relationship("OrderPhoto", back_populates="order")


class OrderSparePart(Base):
    """Связующая таблица: список запчастей на заказ"""
    __tablename__ = "order_spare_parts"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"))
    spare_part_id = Column(BigInteger, ForeignKey("spare_parts.id"))
    quantity = Column(Integer)  # кол-во

    # Связи
    order = relationship("Order", back_populates="spare_parts_list")
    spare_part = relationship("SparePart") # Можно добавить back_populates, если нужно


class OrderPhoto(Base):
    __tablename__ = "order_photos"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"))
    photo_url = Column(Text)    # фото (ссылка)
    photo_type = Column(Boolean) # тип фото (до/после) - bool: True = после, False = до

    # Связи
    order = relationship("Order", back_populates="photos")