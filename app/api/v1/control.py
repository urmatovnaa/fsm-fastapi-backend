from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.inventory import SparePart, Technique, Warehouse
from app.models.users import User
from app.schemas.inventory import (
    SparePartResponse,
    TechniqueResponse,
    WarehouseResponse,
)

router = APIRouter(prefix="/control", tags=["Control"])


@router.get("/techniques", response_model=list[TechniqueResponse])
async def list_techniques(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Technique))
    return result.scalars().all()


@router.post(
    "/techniques",
    response_model=TechniqueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_technique(
    name: str,
    model_parameters: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    technique = Technique(name=name, model_parameters=model_parameters)
    session.add(technique)
    await session.commit()
    await session.refresh(technique)
    return technique


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
    name: str,
    type: str | None = None,
    description: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    spare_part = SparePart(name=name, type=type, description=description)
    session.add(spare_part)
    await session.commit()
    await session.refresh(spare_part)
    return spare_part