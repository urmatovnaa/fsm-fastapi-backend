from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import (
    ORDER_TRANSITIONS,
    REQUEST_TRANSITIONS,
    OrderStatuses,
    RequestStatuses,
    is_valid_transition,
)
from app.models.orders import Order, OrderWorker, Request, Status
from app.schemas.orders import RequestCreate

# Терминальные статусы заказа: заказ больше не активен, по заявке можно
# создавать новый заказ (в т.ч. после NOT_COMPLETED).
TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatuses.COMPLETED,
        OrderStatuses.NOT_COMPLETED,
        OrderStatuses.CANCELLED,
    }
)


def utc_now() -> datetime:
    """Naive UTC timestamp для колонок TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderNotFound(Exception):
    ...


class InvalidOrderState(Exception):
    """Недопустимый переход статуса (нарушение бизнес-логики)."""


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


async def _status_name(session: AsyncSession, status_id: int | None) -> str | None:
    if status_id is None:
        return None
    result = await session.execute(select(Status.name).where(Status.id == status_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Централизованная валидация переходов статусов
# ---------------------------------------------------------------------------
async def validate_transition(
    session: AsyncSession,
    *,
    status_id: int | None,
    target: str,
    transitions: dict[str, frozenset[str]],
) -> None:
    """Проверяет допустимость перехода текущего статуса в целевой.

    Единая точка валидации: и заявки, и заказы проходят проверку здесь,
    что не позволяет API произвольно выставлять несовместимые статусы.
    """
    current = await _status_name(session, status_id)
    if not is_valid_transition(current, target, transitions):
        raise InvalidOrderState(f"{current!r} -> {target!r}")


async def _apply_order_status(
    session: AsyncSession,
    *,
    order: Order,
    target: str,
) -> Status:
    """Валидирует и применяет целевой статус заказа."""
    await validate_transition(
        session,
        status_id=order.status_id,
        target=target,
        transitions=ORDER_TRANSITIONS,
    )
    status = await _require_status(session, target)
    order.status_id = status.id
    return status


async def _apply_request_status(
    session: AsyncSession,
    *,
    request: Request,
    target: str,
) -> Status:
    """Валидирует и применяет целевой статус заявки."""
    await validate_transition(
        session,
        status_id=request.status_id,
        target=target,
        transitions=REQUEST_TRANSITIONS,
    )
    status = await _require_status(session, target)
    request.status_id = status.id
    return status


# ---------------------------------------------------------------------------
# Заявки
# ---------------------------------------------------------------------------
async def create_request(
    session: AsyncSession,
    *,
    user_id: int,
    data: RequestCreate,
) -> Request:
    status = await _require_status(session, RequestStatuses.SEARCHING_MASTER)

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


async def reject_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> Request:
    """Заявка отклонена (не может быть выполнена)."""
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound
    await _apply_request_status(
        session, request=request, target=RequestStatuses.REJECTED
    )
    await session.commit()
    await session.refresh(request, attribute_names=["status"])
    return request


async def cancel_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> Request:
    """Заявка отменена."""
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound
    await _apply_request_status(
        session, request=request, target=RequestStatuses.CANCELLED
    )
    await session.commit()
    await session.refresh(request, attribute_names=["status"])
    return request


async def _has_active_order(session: AsyncSession, request_id: int) -> bool:
    """Есть ли у заявки незавершённый заказ."""
    result = await session.execute(
        select(Order.status_id).where(Order.request_id == request_id)
    )
    for (status_id,) in result.all():
        name = await _status_name(session, status_id)
        if name not in TERMINAL_ORDER_STATUSES:
            return True
    return False


async def accept_request(
    session: AsyncSession,
    *,
    request_id: int,
    worker_id: int,
) -> Order:
    """Мастер принимает заявку -> создаётся заказ в статусе ACCEPTED.

    Заявка остаётся в SEARCHING_MASTER до завершения/отмены заказа.
    Повторное принятие блокируется, пока есть активный заказ.
    """
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound

    searching_status = await _require_status(session, RequestStatuses.SEARCHING_MASTER)
    if request.status_id != searching_status.id:
        raise InvalidOrderState("Request is not in SEARCHING_MASTER state")

    if await _has_active_order(session, request.id):
        raise InvalidOrderState("Request already has an active order")

    accepted_status = await _require_status(session, OrderStatuses.ACCEPTED)

    order = Order(
        request_id=request.id,
        status_id=accepted_status.id,
        appointment_time=utc_now(),
    )
    session.add(order)
    await session.flush()

    # Назначение мастера на заказ + создание заказа — транзакционно.
    session.add(OrderWorker(order_id=order.id, worker_id=worker_id))

    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


# ---------------------------------------------------------------------------
# Заказы
# ---------------------------------------------------------------------------
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


async def _get_worker_order(
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
    return order


async def start_route(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """ACCEPTED -> EN_ROUTE: мастер направляется к клиенту."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.EN_ROUTE)
    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


async def start_work(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """EN_ROUTE -> IN_PROGRESS: работа выполняется."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.IN_PROGRESS)
    order.work_start_time = utc_now()
    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


async def complete_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """IN_PROGRESS -> COMPLETED: работа завершена, заявка -> COMPLETED."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)

    request = await get_request(session, order.request_id)
    if request is None:
        raise OrderNotFound

    await _apply_order_status(session, order=order, target=OrderStatuses.COMPLETED)

    # Транзакционно: заказ завершён + заявка -> COMPLETED.
    order.work_end_time = utc_now()
    if request.status_id != (await _require_status(session, RequestStatuses.COMPLETED)).id:
        await _apply_request_status(
            session, request=request, target=RequestStatuses.COMPLETED
        )

    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


async def not_completed_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """ACCEPTED/EN_ROUTE/IN_PROGRESS -> NOT_COMPLETED: работа не выполнена.

    Заявка остаётся в SEARCHING_MASTER, что позволяет создать новый заказ
    на основании той же заявки.
    """
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.NOT_COMPLETED)
    order.work_end_time = utc_now()
    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order


async def cancel_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """ACCEPTED/EN_ROUTE -> CANCELLED: заказ отменён."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.CANCELLED)
    await session.commit()
    await session.refresh(order, attribute_names=["status"])
    return order