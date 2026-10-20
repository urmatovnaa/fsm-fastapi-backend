"""Пакет ORM-моделей.

Импорт всех моделей необходим, чтобы они были зарегистрированы
в едином `Base.metadata` (используется Alembic для autogenerate миграций).
"""

from app.models.base import Base
from app.models.users import User, Worker, Skill
from app.models.orders import (
    Status,
    Street,
    Request,
    RequestTechnic,
    Schedule,
    Order,
    OrderWorker,
    OrderPart,
    OrderPhoto,
)
from app.models.inventory import (
    Technic,
    SparePart,
    Warehouse,
    WarehouseStock,
)

__all__ = [
    "Base",
    # users
    "User",
    "Worker",
    "Skill",
    # orders
    "Status",
    "Street",
    "Request",
    "RequestTechnic",
    "Schedule",
    "Order",
    "OrderWorker",
    "OrderPart",
    "OrderPhoto",
    # inventory
    "Technic",
    "SparePart",
    "Warehouse",
    "WarehouseStock",
]