"""Пакет ORM-моделей.

Импорт всех моделей необходим, чтобы они были зарегистрированы
в едином `Base.metadata` (используется Alembic для autogenerate миграций).
"""

from app.models.base import Base
from app.models.users import Role, User, Worker, Schedule, Skill
from app.models.orders import (
    Status,
    Street,
    Operation,
    Request,
    RequestTechnique,
    RequestOperation,
    Order,
    OrderPhoto,
    OrderSparePart,
)
from app.models.inventory import (
    Technique,
    Warehouse,
    SparePart,
    WarehouseInventory,
)

__all__ = [
    "Base",
    # users
    "Role",
    "User",
    "Worker",
    "Schedule",
    "Skill",
    # orders
    "Status",
    "Street",
    "Operation",
    "Request",
    "RequestTechnique",
    "RequestOperation",
    "Order",
    "OrderPhoto",
    "OrderSparePart",
    # inventory
    "Technique",
    "Warehouse",
    "SparePart",
    "WarehouseInventory",
]