"""Справочные данные, доступные авторизованным пользователям.

Административные операции (``get_current_admin``) вынесены в отдельный модуль
``app/api/v1/admin.py`` (tag ``Admin``). Здесь остаются только справочные
endpoints, нужные мастерам: их отдаёт любой авторизованный пользователь
(tag ``Worker / Master``).

Группировка Swagger не заменяет проверки прав: доступ контролируется здесь
через зависимость ``get_current_user``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.tags import TAG_WORKER
from app.models.users import User
from app.schemas.inventory import (
    SparePartResponse,
    TechnicResponse,
    WarehouseResponse,
)
from app.services import catalog as catalog_service

router = APIRouter(prefix="/control")

# --- Справочные данные (доступны авторизованным, нужны мастерам) ----------
worker_router = APIRouter(tags=[TAG_WORKER])


@worker_router.get("/technics", response_model=list[TechnicResponse])
async def list_technics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник техники (доступно авторизованным пользователям)."""
    return await catalog_service.list_technics(session)


@worker_router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник складов (доступно авторизованным пользователям)."""
    return await catalog_service.list_warehouses(session)


@worker_router.get("/spare-parts", response_model=list[SparePartResponse])
async def list_spare_parts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник запчастей (доступно авторизованным пользователям)."""
    return await catalog_service.list_spare_parts(session)


router.include_router(worker_router)