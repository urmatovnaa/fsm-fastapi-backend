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
from app.models.inventory import SparePart, Technic
from app.models.orders import (
    Order,
    OrderPart,
    OrderPhoto,
    OrderWorker,
    Request,
    RequestTechnic,
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


class TechnicNotFound(Exception):
    """Указанная единица техники не найдена."""


class OrderAlreadyCreated(Exception):
    """По заявке уже создан заказ — изменение состава техники запрещено."""


class WorkerNotFound(Exception):
    """Работник, который должен быть назначен на заказ, не найден."""


class NotOrderWorker(Exception):
    """Указанный работник не привязан к заказу."""


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
    """Связи заявки вместе со статусами её заказов и составом техники."""
    return (
        selectinload(Request.status),
        selectinload(Request.orders).selectinload(Order.status),
        selectinload(Request.technics).selectinload(RequestTechnic.technic),
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
async def _require_technics(
    session: AsyncSession, technic_ids: list[int]
) -> list[Technic]:
    """Проверяет существование указанной техники и возвращает её записи.

    Дубликаты ID игнорируются (сохраняется порядок первого появления).
    Отсутствующая техника -> ``TechnicNotFound``.
    """
    if not technic_ids:
        return []

    unique_ids = list(dict.fromkeys(technic_ids))
    result = await session.execute(
        select(Technic).where(Technic.id.in_(unique_ids))
    )
    found = {t.id: t for t in result.scalars().all()}
    missing = [tid for tid in unique_ids if tid not in found]
    if missing:
        raise TechnicNotFound(missing)
    return [found[tid] for tid in unique_ids]


async def create_request(
    session: AsyncSession,
    *,
    user_id: int,
    data: RequestCreate,
) -> Request:
    """Создаёт заявку текущего пользователя со статусом SEARCHING_MASTER.

    ``user_id`` всегда берётся из авторизованного пользователя — передать
    произвольный идентификатор через тело запроса нельзя. Указанная техника
    сохраняется через существующую связь ``RequestTechnic`` (новые таблицы/
    поля не создаются).
    """
    status = await _require_status(session, RequestStatuses.SEARCHING_MASTER)
    technics = await _require_technics(session, data.technic_ids)

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
    for technic in technics:
        request.technics.append(RequestTechnic(technic=technic))
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


async def add_request_technics(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
    technic_ids: list[int],
) -> Request:
    """Меняет состав техники существующей заявки пользователя.

    Допустимо только пока по заявке не создан заказ (работник не назначен),
    то есть заявка находится в статусе ``SEARCHING_MASTER`` и связанных
    ``Order`` нет. В этом случае состав ``RequestTechnic`` заменяется на
    переданный (сценарий А). Новый ``Order`` не создаётся.

    Если заказ уже создан (работник назначен), изменение запрещено — возбуждается
    ``OrderAlreadyCreated`` (сценарий Б): заявка не меняется, новый ``Order`` не
    создаётся.
    """
    request = await get_request(session, request_id)
    if request is None:
        raise OrderNotFound("Request not found")
    if request.user_id != user_id:
        raise NotOrderOwner

    # Сценарий Б: заказ уже создан (по статусу заявки или наличию Order).
    status_name = (
        request.status.name if request.status is not None else None
    )
    has_orders = len(request.orders) > 0
    if has_orders or status_name != RequestStatuses.SEARCHING_MASTER:
        raise OrderAlreadyCreated

    technics = await _require_technics(session, technic_ids)

    # Заменяем состав техники заявки (сценарий А).
    unique_ids = list(dict.fromkeys(technic_ids))
    desired = set(unique_ids)
    existing_by_technic = {link.technic_id: link for link in request.technics}

    # Удаляем технику, которой больше нет в новом составе.
    for link in list(request.technics):
        if link.technic_id not in desired:
            request.technics.remove(link)
            await session.delete(link)

    # Добавляем отсутствующие связи (существующие не пересоздаём, чтобы не
    # конфликтовать по составному PK request_id + technic_id).
    by_id = {t.id: t for t in technics}
    for technic_id in unique_ids:
        if technic_id not in existing_by_technic:
            request.technics.append(RequestTechnic(technic=by_id[technic_id]))

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
# Административный просмотр заявок, заказов и отзывов
# ---------------------------------------------------------------------------
def _admin_order_options():
    """Связи заказа для административного просмотра (включая работников)."""
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
    """Связи заявки для административного просмотра (владелец + заказы).

    Заказы заявки предзагружаются полностью (статус, запрос, запчасти,
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
    * ``worker_id`` — отбор заявок, связанных с заказами этого работника.

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
    """Список заказов для администратора с фильтрами и пагинацией."""
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
    """Заказ для администратора со всеми связанными данными."""
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


# ---------------------------------------------------------------------------
# Административное управление статусом заявки и работниками заказа
# ---------------------------------------------------------------------------
# Имена, которыми в проекте обозначается отмена заявки. ``CANCELED`` (одна L)
# принимается наравне с каноническим ``CANCELLED`` — структура БД не меняется,
# соответствующая запись берётся из существующей таблицы ``statuses``.
_REQUEST_CANCEL_NAMES = frozenset(
    {RequestStatuses.CANCELLED, "CANCELED"}
)
_REQUEST_CANCELED_NOTIFICATION = "REQUEST_CANCELED"


async def list_statuses(session: AsyncSession) -> list[Status]:
    """Существующий справочник статусов (для выбора администратором)."""
    result = await session.execute(select(Status).order_by(Status.id))
    return list(result.scalars().all())


async def _resolve_status(
    session: AsyncSession,
    *,
    status_id: int | None,
    status_name: str | None,
) -> Status:
    """Находит запись статуса по ID или имени в существующем справочнике.

    Дополнительно поддерживает алиас ``CANCELED`` -> ``CANCELLED`` и обратное,
    чтобы существующая система статусов оставалась единой.
    """
    status: Status | None = None
    if status_id is not None:
        status = await session.get(Status, status_id)
    elif status_name is not None:
        status = await get_status_by_name(session, status_name)
        if status is None and status_name in _REQUEST_CANCEL_NAMES:
            # Пробуем альтернативное написание отмены.
            for candidate in _REQUEST_CANCEL_NAMES:
                status = await get_status_by_name(session, candidate)
                if status is not None:
                    break
    if status is None:
        raise StatusNotFound(status_id if status_id is not None else status_name)
    return status


async def admin_set_request_status(
    session: AsyncSession,
    *,
    request_id: int,
    status_id: int | None = None,
    status_name: str | None = None,
) -> tuple[Request, dict | None]:
    """Администратор вручную задаёт существующий статус заявки.

    Проверяются существование заявки и указанного статуса. При переводе заявки
    в статус отмены формируется уведомление владельцу. Отдельная таблица
    уведомлений не создаётся — уведомление возвращается как данные.

    Возвращает пару ``(request, notification | None)``.
    """
    request = await get_admin_request(session, request_id)
    if request is None:
        raise OrderNotFound("Request not found")

    if status_id is None and status_name is None:
        raise InvalidOrderState("status_id or status_name is required")

    status = await _resolve_status(
        session, status_id=status_id, status_name=status_name
    )

    request.status_id = status.id
    # Синхронизируем загруженную связь, чтобы ответ отражал новый статус.
    request.status = status
    await session.commit()

    # Перезагружаем с административными связями (владелец + заказы + работники),
    # чтобы сериализация не вызывала lazy-load в async-контексте.
    updated = await get_admin_request(session, request_id)

    notification: dict | None = None
    if status.name in _REQUEST_CANCEL_NAMES:
        notification = {
            "type": _REQUEST_CANCELED_NOTIFICATION,
            "user_id": updated.user_id,
            "request_id": updated.id,
            "message": "Ваша заявка была отменена администратором.",
        }

    return updated, notification


async def list_order_workers(
    session: AsyncSession, order_id: int
) -> list[OrderWorker]:
    """Текущие назначения (OrderWorker) конкретного заказа."""
    result = await session.execute(
        select(OrderWorker).where(OrderWorker.order_id == order_id)
    )
    return list(result.scalars().all())


async def change_order_worker(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
    replace_existing: bool = True,
) -> Order:
    """Назначает/заменяет работника заказа через существующую связь OrderWorker.

    * проверяются существование заказа и работника;
    * при ``replace_existing`` текущие назначения удаляются (замена);
    * связанные данные (расписание) не затрагиваются — изменение касается только
      связи работник–заказ, что сохраняет существующую бизнес-логику.

    Новая таблица и отдельное поле для работника не создаются.
    """
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFound("Order not found")

    worker = await session.get(Worker, worker_id)
    if worker is None:
        raise WorkerNotFound(worker_id)

    existing = await list_order_workers(session, order_id)
    already = {ow.worker_id for ow in existing}

    if replace_existing:
        # Замена: убираем прочих, целевого оставляем/добавляем.
        for ow in existing:
            if ow.worker_id != worker_id:
                await session.delete(ow)
        if worker_id not in already:
            session.add(OrderWorker(order_id=order_id, worker_id=worker_id))
    elif worker_id not in already:
        # Добавление второго работника без удаления текущих.
        session.add(OrderWorker(order_id=order_id, worker_id=worker_id))

    await session.commit()
    # Перезагружаем с административными связями (включая работников), чтобы
    # сериализация ответа не вызывала lazy-load в async-контексте.
    return await get_admin_order(session, order_id)


async def remove_order_worker(
    session: AsyncSession,
    *,
    order_id: int,
    worker_id: int,
) -> Order:
    """Удаляет работника из заказа (существующая связь OrderWorker).

    Несуществующее назначение -> ``NotOrderWorker``. Расписание и прочие
    связанные данные не изменяются.
    """
    order = await get_order(session, order_id)
    if order is None:
        raise OrderNotFound("Order not found")

    result = await session.execute(
        select(OrderWorker).where(
            OrderWorker.order_id == order_id,
            OrderWorker.worker_id == worker_id,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise NotOrderWorker(worker_id)

    await session.delete(link)
    await session.commit()
    return await get_admin_order(session, order_id)