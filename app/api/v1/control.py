from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db
from app.models.inventory import SparePart, Technic, Warehouse
from app.models.users import User
from app.schemas.inventory import (
    SparePartCreate,
    SparePartResponse,
    TechnicCreate,
    TechnicResponse,
    WarehouseResponse,
)

router = APIRouter(prefix="/control", tags=["Control"])


@router.get("/technics", response_model=list[TechnicResponse])
async def list_technics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Technic))
    return result.scalars().all()


@router.post(
    "/technics",
    response_model=TechnicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_technic(
    payload: TechnicCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    technic = Technic(name=payload.name, model_params=payload.model_params)
    session.add(technic)
    await session.commit()
    await session.refresh(technic)
    return technic


@router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Warehouse))
    return result.scalars().all()


@router.get("/spare-parts", response_model=list[SparePartResponse])
async def list_spare_parts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(SparePart))
    return result.scalars().all()


@router.post(
    "/spare-parts",
    response_model=SparePartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_spare_part(
    payload: SparePartCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    spare_part = SparePart(
        name=payload.name,
        description=payload.description,
        price=payload.price,
    )
    session.add(spare_part)
    await session.commit()
    await session.refresh(spare_part)
    return spare_part