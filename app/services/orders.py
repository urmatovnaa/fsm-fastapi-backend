from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import StatusNames
from app.models.orders import Order, OrderWorker, Request, Status
from app.schemas.orders import RequestCreate


def utc_now() -> datetime:
    """Naive UTC timestamp для колонок TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderNotFound(Exception):
    ...


class InvalidOrderState(Exception):
    ...


class NotOrderOwner(Exception):
    ...


class StatusNotFound(Exception):
    ...


async def get_status_by_name(session: AsyncSession, name: str) -> Status | None:
    result = await session.execute(select(Status).where(Status.name == name))
    return result.scalar_one_or_none()


async def _require_status(session: AsyncSession, name: str) -> Status:
    status = await get_status_by_name(session, name)
    if status is None:
        raise StatusNotFound(name)
    return status


async def create_request(
    session: AsyncSession,
    *,
    user_id: int,
    data: RequestCreate,
) -> Request:
    status = await _require_status(session, StatusNames.NEW)

    request = Request(
        user_id=user_id,
        status_id=status.id,
        street_id=data.street_id,
        house_number=data.house_number,
        latitude=data.latitude,
        longitude=data.longitude,
        problem_description=data.problem_description,
        urgency=data.urgency,
        visit_date=data.visit_date,
        visit_time_start=data.visit_time_start,
        visit_time_end=data.visit_time_end,
        created_at=utc_now(),
    )
    session.add(request)
    await session.commit()
    await session.refresh(request, attribute_names=["status"])
    return request


async def get_request(session: AsyncSession, request_id: int) -> Request | None:
    result = await session.execute(
        select(Request)
        .options(selectinload(Request.status))
        .where(Request.id == request_id)
    )
    return result.scalar_one_or_none()


async def list_requests(session: AsyncSession) -> list[Request]:
    result = await session.execute(
        select(Request).options(selectinload(Request.status)).order_by(Request.id)
    )
    return list(result.scalars().all())


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order).options(selectinload(Order.status)).where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders(session: AsyncSession, *, worker_id: int) -> list[Order]:
    result = await session.execute(
        select(Order)
        .join(OrderWorker, OrderWorker.order_id == Order.id)
        .options(selectinload(Order.status))
        .where(OrderWorker.worker_id == worker_id)
        .order_by(Order.id)
    )
    return list(result.scalars().all())


async def _is_order_worker(
    session: AsyncSession, *, order_id: int, worker_id: int
) -> bool:
    result = await session.execute(
        select(OrderWorker).where(
            OrderWorker.order_id == order_id,
            OrderWorker.worker_id == worker_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def accept_request(
    session: AsyncSession,
    *,
    request_id: int,
    worker_id: int,
) -> Order:
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound

    new_status = await _require_status(session, StatusNames.NEW)
    if request.status_id != new_status.id:
        raise InvalidOrderState

    assigned_status = await _require_status(session, StatusNames.ASSIGNED)

    order = Order(
        request_id=request.id,
        status_id=assigned_status.id,
        appointment_time=utc_now(),
    )
    session.add(order)
    await session.flush()

    # Назначение мастера на наряд + перевод заявки в ASSIGNED — транзакционно.
    session.add(OrderWorker(order_id=order.id, worker_id=worker_id))
    request.status_id = assigned_status.id

    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


async def complete_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFound

    if not await _is_order_worker(session, order_id=order_id, worker_id=worker_id):
        raise NotOrderOwner

    request = await get_request(session, order.request_id)
    if request is None:
        raise OrderNotFound

    assigned_status = await _require_status(session, StatusNames.ASSIGNED)
    if request.status_id != assigned_status.id:
        raise InvalidOrderState

    done_status = await _require_status(session, StatusNames.DONE)

    # Транзакционно: наряд завершён + заявка -> DONE.
    order.work_end_time = utc_now()
    order.status_id = done_status.id
    request.status_id = done_status.id

    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order