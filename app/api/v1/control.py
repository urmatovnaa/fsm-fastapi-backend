"""API администратора и справочные данные.

Административные операции (``get_current_admin``) сгруппированы в tag
``Admin``. Справочные данные (техника, склады, запчасти) доступны любому
авторизованному пользователю и в первую очередь нужны мастерам, поэтому
сгруппированы в tag ``Worker / Master``.

Группировка Swagger не заменяет проверки прав: доступ контролируется здесь
через зависимости ``get_current_admin``/``get_current_user``.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.tags import TAG_ADMIN, TAG_WORKER
from app.models.inventory import SparePart, Technic, Warehouse
from app.models.users import User
from app.schemas.inventory import (
    SparePartCreate,
    SparePartResponse,
    TechnicCreate,
    TechnicResponse,
    WarehouseResponse,
)
from app.schemas.users import AdminUserResponse
from app.services import users as user_service

router = APIRouter(prefix="/control")

# --- Административные операции -------------------------------------------
admin_router = APIRouter(tags=[TAG_ADMIN])


@admin_router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список всех пользователей (user/worker/admin). Только для админа."""
    users = await user_service.list_users(session)
    return [
        AdminUserResponse(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            phone=u.phone,
            is_admin=bool(u.is_admin),
            worker_id=u.worker_profile.id if u.worker_profile else None,
        )
        for u in users
    ]


@admin_router.post(
    "/technics",
    response_model=TechnicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_technic(
    payload: TechnicCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создание техники. Только для админа."""
    technic = Technic(name=payload.name, model_params=payload.model_params)
    session.add(technic)
    await session.commit()
    await session.refresh(technic)
    return technic


@admin_router.post(
    "/spare-parts",
    response_model=SparePartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_spare_part(
    payload: SparePartCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создание запчасти (справочник). Только для админа."""
    spare_part = SparePart(
        name=payload.name,
        description=payload.description,
        price=payload.price,
    )
    session.add(spare_part)
    await session.commit()
    await session.refresh(spare_part)
    return spare_part


# --- Справочные данные (доступны авторизованным, нужны мастерам) ----------
worker_router = APIRouter(tags=[TAG_WORKER])


@worker_router.get("/technics", response_model=list[TechnicResponse])
async def list_technics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник техники (доступно авторизованным пользователям)."""
    result = await session.execute(select(Technic))
    return result.scalars().all()


@worker_router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник складов (доступно авторизованным пользователям)."""
    result = await session.execute(select(Warehouse))
    return result.scalars().all()


@worker_router.get("/spare-parts", response_model=list[SparePartResponse])
async def list_spare_parts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Справочник запчастей (доступно авторизованным пользователям)."""
    result = await session.execute(select(SparePart))
    return result.scalars().all()


router.include_router(admin_router)
router.include_router(worker_router)