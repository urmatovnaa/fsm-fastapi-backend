from sqlalchemy import Column, BigInteger, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    is_admin = Column(Boolean, default=False)
    full_name = Column(String, nullable=True)  # ФИО
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)      # телефон
    password = Column(String)                  # пароль (хранить хэш!)

    # Связи
    worker_profile = relationship("Worker", back_populates="user", uselist=False)
    applications = relationship("Application", back_populates="user")


class Worker(Base):
    __tablename__ = "workers"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    latitude = Column(Integer, nullable=True)   # широта
    longitude = Column(Integer, nullable=True)  # долгота
    experience = Column(Integer, nullable=True) # стаж работы

    # Связи
    user = relationship("User", back_populates="worker_profile")
    skills = relationship("Skill", back_populates="worker")
    schedules = relationship("Schedule", back_populates="worker")
    orders = relationship("Order", back_populates="worker")


class Skill(Base):
    __tablename__ = "skills"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"))
    equipment_id = Column(BigInteger, ForeignKey("equipment.id"))

    # Связи
    worker = relationship("Worker", back_populates="skills")
    equipment = relationship("Equipment", back_populates="skills")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"))
    day_of_week = Column(String)      # день недели
    start_time = Column(DateTime)     # время начала работы
    end_time = Column(DateTime)       # время конца работы

    # Связи
    worker = relationship("Worker", back_populates="schedules")