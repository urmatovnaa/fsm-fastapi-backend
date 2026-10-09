from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, Interval
from sqlalchemy.orm import relationship
from .base import Base

class Role(Base):
    __tablename__ = "roles"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    rights = Column(Text, nullable=True)

    users = relationship("User", back_populates="role")

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    role_id = Column(BigInteger, ForeignKey("roles.id"), nullable=True)
    full_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    password = Column(String, nullable=True)

    role = relationship("Role", back_populates="users")
    worker = relationship("Worker", back_populates="user", uselist=False)
    requests = relationship("Request", back_populates="user")

class Worker(Base):
    __tablename__ = "workers"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    latitude = Column(Integer, nullable=True)
    longitude = Column(Integer, nullable=True)
    experience = Column(Integer, nullable=True)

    user = relationship("User", back_populates="worker")
    schedules = relationship("Schedule", back_populates="worker")
    skills = relationship("Skill", back_populates="worker")
    orders = relationship("Order", back_populates="worker")

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=True)
    day_of_week = Column(String, nullable=True)
    working_hours = Column(Interval, nullable=True)

    worker = relationship("Worker", back_populates="schedules")

class Skill(Base):
    __tablename__ = "skills"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    worker_id = Column(BigInteger, ForeignKey("workers.id"), nullable=True)
    operation_id = Column(BigInteger, ForeignKey("operations.id"), nullable=True)

    worker = relationship("Worker", back_populates="skills")
    operation = relationship("Operation", back_populates="skills")
