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
from app.models.inventory import SparePart
from app.models.orders import (
    Order,
    OrderPart,
    OrderPhoto,
    OrderWorker,
    Request,
    Status,
)
from app.models.users import Worker
from app.schemas.orders import OrderPartCreate, OrderPhotoCreate, RequestCreate

# Терминальные статусы заказа: заказ больше не активен.
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


class SparePartNotFound(Exception):
    ...


# ---------------------------------------------------------------------------
# Eager loading: избегаем lazy-load в async-контексте и N+1.
# ---------------------------------------------------------------------------
def _order_options():
    """Полный набор связей заказа для API-ответа."""
    return (
        selectinload(Order.status),
        selectinload(Order.request).selectinload(Request.status),
        selectinload(Order.parts).selectinload(OrderPart.spare_part),
        selectinload(Order.photos),
    )


def _request_options():
    """Связи заявки вместе со статусами её заказов."""
    return (
        selectinload(Request.status),
        selectinload(Request.orders).selectinload(Order.status),
    )


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
    # Синхронизируем загруженную связь, чтобы ответ API отражал новый статус
    # (иначе в identity map остаётся прежний объект статуса).
    order.status = status
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
    request.status = status
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
    """Создаёт заявку текущего пользователя со статусом SEARCHING_MASTER.

    ``user_id`` всегда берётся из авторизованного пользователя — передать
    произвольный идентификатор через тело запроса нельзя.
    """
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
    return await get_request(session, request.id)


async def get_request(session: AsyncSession, request_id: int) -> Request | None:
    result = await session.execute(
        select(Request)
        .options(*_request_options())
        .where(Request.id == request_id)
    )
    return result.scalar_one_or_none()


async def list_requests(
    session: AsyncSession,
    *,
    user_id: int | None = None,
) -> list[Request]:
    """Список заявок. При ``user_id`` — только заявки этого пользователя."""
    stmt = (
        select(Request)
        .options(*_request_options())
        .order_by(Request.id)
    )
    if user_id is not None:
        stmt = stmt.where(Request.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def reject_request(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int | None = None,
) -> Request:
    """Заявка отклонена (не может быть выполнена)."""
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound
    if user_id is not None and request.user_id != user_id:
        raise NotOrderOwner
    await _apply_request_status(
        session, request=request, target=RequestStatuses.REJECTED
    )
    await session.commit()
    return await get_request(session, request_id)


async def cancel_request(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int | None = None,
) -> Request:
    """Заявка отменена."""
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound
    if user_id is not None and request.user_id != user_id:
        raise NotOrderOwner
    await _apply_request_status(
        session, request=request, target=RequestStatuses.CANCELLED
    )
    await session.commit()
    return await get_request(session, request_id)


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
    """Мастер принимает заявку -> создаётся заказ, заявка переходит в COMPLETED.

    Ключевое бизнес-правило: как только на основании заявки создан заказ и
    назначен работник, заявка сразу получает статус COMPLETED. Это означает,
    что этап поиска и назначения работника завершён, а дальнейший ход работ
    отслеживается по статусу заказа.

    Операция транзакционная: создание заказа, назначение мастера и смена
    статуса заявки происходят вместе.
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

    # Назначение мастера на заказ.
    session.add(OrderWorker(order_id=order.id, worker_id=worker_id))

    # Заявка сразу завершает этап поиска: SEARCHING_MASTER -> COMPLETED.
    await _apply_request_status(
        session, request=request, target=RequestStatuses.COMPLETED
    )

    await session.commit()
    return await get_order(session, order.id)


# ---------------------------------------------------------------------------
# Заказы
# ---------------------------------------------------------------------------
async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order).options(*_order_options()).where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders(session: AsyncSession, *, worker_id: int) -> list[Order]:
    """Все заказы, назначенные конкретному мастеру (связанные данные включены)."""
    result = await session.execute(
        select(Order)
        .join(OrderWorker, OrderWorker.order_id == Order.id)
        .options(*_order_options())
        .where(OrderWorker.worker_id == worker_id)
        .order_by(Order.id)
    )
    return list(result.scalars().unique().all())


async def list_order_history(
    session: AsyncSession,
    *,
    worker_id: int,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    """История заказов мастера: только его прошлые (терминальные) заказы.

    Фильтрация по статусу — если передан конкретный статус, он должен
    принадлежать набору терминальных статусов заказа.
    """
    stmt = (
        select(Order)
        .join(OrderWorker, OrderWorker.order_id == Order.id)
        .join(Status, Status.id == Order.status_id)
        .options(*_order_options())
        .where(OrderWorker.worker_id == worker_id)
    )
    if status is not None:
        if status not in TERMINAL_ORDER_STATUSES:
            raise InvalidOrderState("Only terminal order statuses are in history")
        stmt = stmt.where(Status.name == status)
    else:
        stmt = stmt.where(Status.name.in_(TERMINAL_ORDER_STATUSES))

    stmt = stmt.order_by(Order.id.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


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
    return await get_order(session, order_id)


async def start_work(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """EN_ROUTE -> IN_PROGRESS: работа выполняется.

    ``work_start_time`` устанавливается только при допустимом переходе, поэтому
    повторный вызов не перезапишет время начала (переход IN_PROGRESS -> IN_PROGRESS
    недопустим и вернёт ошибку).
    """
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.IN_PROGRESS)
    order.work_start_time = utc_now()
    await session.commit()
    return await get_order(session, order_id)


async def update_report(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
    checklist: str | None = None,
    work_description: str | None = None,
    total_amount=None,
) -> Order:
    """Заполнение/обновление отчёта о выполненной работе.

    Чужие заказы недоступны (проверка принадлежности мастеру).
    """
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)

    if checklist is not None:
        order.checklist = checklist
    if work_description is not None:
        order.work_description = work_description
    if total_amount is not None:
        order.total_amount = total_amount

    await session.commit()
    return await get_order(session, order_id)


async def add_order_part(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
    data: OrderPartCreate,
) -> Order:
    """Фиксация использованной запчасти (без складского учёта)."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)

    spare_part = None
    if data.spare_part_id is not None:
        spare_part = await session.get(SparePart, data.spare_part_id)
        if spare_part is None:
            raise SparePartNotFound(data.spare_part_id)

    order.parts.append(
        OrderPart(spare_part_id=data.spare_part_id, quantity=data.quantity)
    )
    if spare_part is not None:
        # Держим связь в памяти, чтобы имя запчасти попало в ответ.
        order.parts[-1].spare_part = spare_part

    await session.commit()
    return await get_order(session, order_id)


async def add_order_photo(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
    data: OrderPhotoCreate,
) -> Order:
    """Добавление фотографии результата, связанной с заказом."""
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    order.photos.append(
        OrderPhoto(photo_url=data.photo_url, photo_type=data.photo_type)
    )
    await session.commit()
    return await get_order(session, order_id)


async def complete_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """IN_PROGRESS -> COMPLETED: работа завершена.

    Статус заявки не меняется повторно: она уже перешла в COMPLETED на этапе
    создания заказа и назначения мастера.
    """
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.COMPLETED)
    order.work_end_time = utc_now()
    await session.commit()
    return await get_order(session, order_id)


async def not_completed_order(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """ACCEPTED/EN_ROUTE/IN_PROGRESS -> NOT_COMPLETED: работа не выполнена.

    Статус заявки не откатывается автоматически: она остаётся в COMPLETED
    (этап поиска и назначения мастера уже завершён).
    """
    order = await _get_worker_order(session, order_id=order_id, worker_id=worker_id)
    await _apply_order_status(session, order=order, target=OrderStatuses.NOT_COMPLETED)
    order.work_end_time = utc_now()
    await session.commit()
    return await get_order(session, order_id)


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
    return await get_order(session, order_id)


# ---------------------------------------------------------------------------
# Доступ пользователя (клиента)
# ---------------------------------------------------------------------------
async def _get_user_request(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
) -> Request:
    """Заявка пользователя; чужая заявка не раскрывается (NotOrderOwner)."""
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound
    if request.user_id != user_id:
        raise NotOrderOwner
    return request


async def get_user_request(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
) -> Request:
    """Публичная обёртка проверки владения заявкой."""
    return await _get_user_request(session, request_id=request_id, user_id=user_id)


async def list_user_orders(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
) -> list[Order]:
    """Все заказы по заявке пользователя (последний — сверху)."""
    await _get_user_request(session, request_id=request_id, user_id=user_id)
    result = await session.execute(
        select(Order)
        .options(*_order_options())
        .where(Order.request_id == request_id)
        .order_by(Order.id.desc())
    )
    return list(result.scalars().unique().all())


async def get_request_result(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
) -> Order | None:
    """Результат работы по заявке пользователя (самый свежий заказ)."""
    orders = await list_user_orders(session, request_id=request_id, user_id=user_id)
    return orders[0] if orders else None


async def add_client_review(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
    review: str,
) -> Order:
    """Отзыв клиента по завершённому заказу своей заявки.

    Возможность отзыва определяется завершённостью именно заказа
    (статус ``COMPLETED``), а не статусом заявки.
    """
    await _get_user_request(session, request_id=request_id, user_id=user_id)

    result = await session.execute(
        select(Order)
        .join(Status, Status.id == Order.status_id)
        .options(*_order_options())
        .where(
            Order.request_id == request_id,
            Status.name == OrderStatuses.COMPLETED,
        )
        .order_by(Order.id.desc())
    )
    order = result.scalars().unique().first()
    if order is None:
        raise InvalidOrderState("Request has no completed order to review")

    if order.client_review:
        raise InvalidOrderState("Review has already been submitted")

    order.client_review = review
    await session.commit()
    return await get_order(session, order.id)


# ---------------------------------------------------------------------------
# Административный просмотр заявок, нарядов и отзывов
# ---------------------------------------------------------------------------
def _admin_order_options():
    """Связи наряда для административного просмотра (включая работников)."""
    return (
        selectinload(Order.status),
        selectinload(Order.request).selectinload(Request.status),
        selectinload(Order.request).selectinload(Request.user),
        selectinload(Order.parts).selectinload(OrderPart.spare_part),
        selectinload(Order.photos),
        selectinload(Order.workers)
        .selectinload(OrderWorker.worker)
        .selectinload(Worker.user),
    )


def _admin_request_options():
    """Связи заявки для административного просмотра (владелец + наряды).

    Наряды заявки предзагружаются полностью (статус, запрос, запчасти,
    фотографии, назначенные работники), чтобы сериализация не вызывала
    lazy-load в async-контексте.
    """
    return (
        selectinload(Request.status),
        selectinload(Request.user),
        selectinload(Request.orders).selectinload(Order.status),
        selectinload(Request.orders)
        .selectinload(Order.request)
        .selectinload(Request.status),
        selectinload(Request.orders)
        .selectinload(Order.parts)
        .selectinload(OrderPart.spare_part),
        selectinload(Request.orders).selectinload(Order.photos),
        selectinload(Request.orders)
        .selectinload(Order.workers)
        .selectinload(OrderWorker.worker)
        .selectinload(Worker.user),
    )


async def list_admin_requests(
    session: AsyncSession,
    *,
    status: str | None = None,
    user_id: int | None = None,
    worker_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Request]:
    """Список заявок для администратора с фильтрами и пагинацией.

    * ``status`` — имя статуса из справочника ``Status``;
    * ``user_id`` — отбор заявок указанного пользователя;
    * ``worker_id`` — отбор заявок, связанных с нарядами этого работника.

    Фильтры комбинируются. Сортировка предсказуемая — по возрастанию ``id``.
    """
    stmt = select(Request).options(*_admin_request_options())

    if status is not None:
        stmt = stmt.join(Status, Status.id == Request.status_id).where(
            Status.name == status
        )
    if user_id is not None:
        stmt = stmt.where(Request.user_id == user_id)
    if worker_id is not None:
        stmt = stmt.join(Order, Order.request_id == Request.id).join(
            OrderWorker, OrderWorker.order_id == Order.id
        ).where(OrderWorker.worker_id == worker_id)

    stmt = stmt.order_by(Request.id).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_admin_request(
    session: AsyncSession, request_id: int
) -> Request | None:
    """Полная заявка для администратора (без ограничений владения)."""
    result = await session.execute(
        select(Request)
        .options(*_admin_request_options())
        .where(Request.id == request_id)
    )
    return result.scalar_one_or_none()


async def list_admin_orders(
    session: AsyncSession,
    *,
    worker_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    """Список нарядов для администратора с фильтрами и пагинацией."""
    stmt = select(Order).options(*_admin_order_options())
    if worker_id is not None:
        stmt = stmt.join(OrderWorker, OrderWorker.order_id == Order.id).where(
            OrderWorker.worker_id == worker_id
        )
    if status is not None:
        stmt = stmt.join(Status, Status.id == Order.status_id).where(
            Status.name == status
        )
    stmt = stmt.order_by(Order.id).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_admin_order(session: AsyncSession, order_id: int) -> Order | None:
    """Наряд для администратора со всеми связанными данными."""
    result = await session.execute(
        select(Order).options(*_admin_order_options()).where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_reviews(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    """Заказы с оставленными отзывами (``client_review`` не пуст).

    Заказы без отзыва в выборку не попадают. Сортировка — по ``id``.
    """
    stmt = (
        select(Order)
        .options(*_admin_order_options())
        .where(Order.client_review.is_not(None), Order.client_review != "")
    )
    if user_id is not None:
        stmt = stmt.join(Request, Request.id == Order.request_id).where(
            Request.user_id == user_id
        )
    stmt = stmt.order_by(Order.id).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_review(session: AsyncSession, order_id: int) -> Order | None:
    """Отзыв по конкретному заказу (``None``, если отзыва нет)."""
    result = await session.execute(
        select(Order)
        .options(*_admin_order_options())
        .where(
            Order.id == order_id,
            Order.client_review.is_not(None),
            Order.client_review != "",
        )
    )
    return result.scalar_one_or_none()