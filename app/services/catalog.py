"""Сервис справочников и складских остатков (административное управление).

Использует только существующие модели ``Technic``, ``SparePart``,
``Warehouse``, ``WarehouseStock`` и ``Street`` — структура БД не меняется.
Складского учёта в смысле списания/движения нет: сервис управляет лишь
записями остатков (warehouse_id, spare_part_id, quantity).
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inventory import SparePart, Technic, Warehouse, WarehouseStock
from app.models.orders import Street


class TechnicNotFound(Exception):
    ...


class SparePartNotFound(Exception):
    ...


class WarehouseNotFound(Exception):
    ...


class StreetNotFound(Exception):
    ...


class WarehouseStockNotFound(Exception):
    ...


class WarehouseStockConflict(Exception):
    """Остаток для пары (warehouse_id, spare_part_id) уже существует."""


class InvalidQuantity(Exception):
    ...


# ---------------------------------------------------------------------------
# Техника
# ---------------------------------------------------------------------------
async def list_technics(session: AsyncSession) -> list[Technic]:
    result = await session.execute(select(Technic).order_by(Technic.id))
    return list(result.scalars().all())


async def get_technic(session: AsyncSession, technic_id: int) -> Technic | None:
    return await session.get(Technic, technic_id)


async def create_technic(
    session: AsyncSession, *, name: str, model_params: str | None = None
) -> Technic:
    technic = Technic(name=name, model_params=model_params)
    session.add(technic)
    await session.commit()
    await session.refresh(technic)
    return technic


async def update_technic(
    session: AsyncSession,
    *,
    technic: Technic,
    name: str | None = None,
    model_params: str | None = None,
) -> Technic:
    if name is not None:
        technic.name = name
    if model_params is not None:
        technic.model_params = model_params
    await session.commit()
    await session.refresh(technic)
    return technic


# ---------------------------------------------------------------------------
# Запчасти
# ---------------------------------------------------------------------------
async def list_spare_parts(session: AsyncSession) -> list[SparePart]:
    result = await session.execute(select(SparePart).order_by(SparePart.id))
    return list(result.scalars().all())


async def get_spare_part(session: AsyncSession, spare_part_id: int) -> SparePart | None:
    return await session.get(SparePart, spare_part_id)


async def create_spare_part(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    price: Decimal | None = None,
) -> SparePart:
    spare_part = SparePart(name=name, description=description, price=price)
    session.add(spare_part)
    await session.commit()
    await session.refresh(spare_part)
    return spare_part


async def update_spare_part(
    session: AsyncSession,
    *,
    spare_part: SparePart,
    name: str | None = None,
    description: str | None = None,
    price: Decimal | None = None,
) -> SparePart:
    if name is not None:
        spare_part.name = name
    if description is not None:
        spare_part.description = description
    if price is not None:
        spare_part.price = price
    await session.commit()
    await session.refresh(spare_part)
    return spare_part


# ---------------------------------------------------------------------------
# Склады
# ---------------------------------------------------------------------------
async def list_warehouses(session: AsyncSession) -> list[Warehouse]:
    result = await session.execute(
        select(Warehouse).options(selectinload(Warehouse.street)).order_by(Warehouse.id)
    )
    return list(result.scalars().all())


async def get_warehouse(session: AsyncSession, warehouse_id: int) -> Warehouse | None:
    result = await session.execute(
        select(Warehouse)
        .options(selectinload(Warehouse.street))
        .where(Warehouse.id == warehouse_id)
    )
    return result.scalar_one_or_none()


async def _validate_street(session: AsyncSession, street_id: int | None) -> None:
    if street_id is not None and await session.get(Street, street_id) is None:
        raise StreetNotFound(street_id)


async def create_warehouse(
    session: AsyncSession,
    *,
    name: str,
    street_id: int | None = None,
    house_number: int | None = None,
) -> Warehouse:
    await _validate_street(session, street_id)
    warehouse = Warehouse(name=name, street_id=street_id, house_number=house_number)
    session.add(warehouse)
    await session.commit()
    return await get_warehouse(session, warehouse.id)


async def update_warehouse(
    session: AsyncSession,
    *,
    warehouse: Warehouse,
    name: str | None = None,
    street_id: int | None = None,
    house_number: int | None = None,
) -> Warehouse:
    if street_id is not None:
        await _validate_street(session, street_id)
        warehouse.street_id = street_id
    if name is not None:
        warehouse.name = name
    if house_number is not None:
        warehouse.house_number = house_number
    await session.commit()
    return await get_warehouse(session, warehouse.id)


# ---------------------------------------------------------------------------
# Складские остатки
# ---------------------------------------------------------------------------
async def list_warehouse_stocks(
    session: AsyncSession,
    *,
    warehouse_id: int | None = None,
    spare_part_id: int | None = None,
) -> list[WarehouseStock]:
    """Остатки с раскрытыми запчастью и складом (без N+1)."""
    stmt = (
        select(WarehouseStock)
        .options(
            selectinload(WarehouseStock.spare_part),
            selectinload(WarehouseStock.warehouse).selectinload(Warehouse.street),
        )
        .order_by(WarehouseStock.id)
    )
    if warehouse_id is not None:
        stmt = stmt.where(WarehouseStock.warehouse_id == warehouse_id)
    if spare_part_id is not None:
        stmt = stmt.where(WarehouseStock.spare_part_id == spare_part_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_warehouse_stock(
    session: AsyncSession, stock_id: int
) -> WarehouseStock | None:
    result = await session.execute(
        select(WarehouseStock)
        .options(
            selectinload(WarehouseStock.spare_part),
            selectinload(WarehouseStock.warehouse).selectinload(Warehouse.street),
        )
        .where(WarehouseStock.id == stock_id)
    )
    return result.scalar_one_or_none()


async def create_warehouse_stock(
    session: AsyncSession,
    *,
    warehouse_id: int,
    spare_part_id: int,
    quantity: int,
) -> WarehouseStock:
    """Создаёт остаток с проверкой склада, запчасти и количества.

    Повторная запись для пары (warehouse_id, spare_part_id) запрещена —
    изменение количества выполняется через ``update_warehouse_stock``.
    """
    if quantity < 0:
        raise InvalidQuantity(quantity)
    if await get_warehouse(session, warehouse_id) is None:
        raise WarehouseNotFound(warehouse_id)
    if await get_spare_part(session, spare_part_id) is None:
        raise SparePartNotFound(spare_part_id)

    existing = await session.execute(
        select(WarehouseStock).where(
            WarehouseStock.warehouse_id == warehouse_id,
            WarehouseStock.spare_part_id == spare_part_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise WarehouseStockConflict((warehouse_id, spare_part_id))

    stock = WarehouseStock(
        warehouse_id=warehouse_id,
        spare_part_id=spare_part_id,
        quantity=quantity,
    )
    session.add(stock)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise WarehouseStockConflict((warehouse_id, spare_part_id))
    return await get_warehouse_stock(session, stock.id)


async def update_warehouse_stock(
    session: AsyncSession, *, stock: WarehouseStock, quantity: int
) -> WarehouseStock:
    if quantity < 0:
        raise InvalidQuantity(quantity)
    stock.quantity = quantity
    await session.commit()
    return await get_warehouse_stock(session, stock.id)