from sqlalchemy import Column, BigInteger, String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    is_admin = Column(Boolean, default=False)
    full_name = Column(String, nullable=False) # ФИО
    email = Column(String, nullable=False, unique=True) # Корректировка 2: not null
    phone = Column(String, nullable=True)
    password = Column(String, nullable=False)

    # Связи
    worker_profile = relationship("Worker", back_populates="user", uselist=False)

class Worker(Base):
    __tablename__ = "workers"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    latitude = Column(Integer, nullable=True) # широта
    longitude = Column(Integer, nullable=True) # долгота
    experience = Column(Integer, nullable=True) # стаж работы

    # Связи
    user = relationship("User", back_populates="worker_profile")
    skills = relationship("Skill", back_populates="worker")
    schedules = relationship("Schedule", back_populates="worker")
    orders = relationship("OrderWorker", back_populates="worker")

class Skill(Base):
    __tablename__ = "skills"

    id = Column(BigInteger, primary_key=True, index=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=False)
    technic_id = Column(BigInteger, ForeignKey("technics.id"), nullable=True) # Предполагаем связь с техникой

    worker = relationship("Worker", back_populates="skills")
    technic = relationship("Technic") # Связь будет определена в inventory.py