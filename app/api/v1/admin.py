"""Административный API (tag ``Admin``).

Все эндпоинты защищены серверной проверкой ``get_current_admin`` (HTTP 403 для
пользователей без флага ``User.is_admin``). Группировка Swagger по ролям не
заменяет проверки прав.

Структура БД не меняется: используются существующие модели, поля и связи.
Складского учёта в смысле списания остатков нет — управляются только записи
``WarehouseStock``.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.tags import TAG_ADMIN
from app.models.inventory import Warehouse, WarehouseStock
from app.models.orders import Order, Request, Status
from app.models.users import User, Worker
from app.schemas.inventory import (
    SparePartCreate,
    SparePartResponse,
    SparePartUpdate,
    TechnicCreate,
    TechnicResponse,
    TechnicUpdate,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
    WarehouseStockCreate,
    WarehouseStockDetailResponse,
    WarehouseStockUpdate,
)
from app.schemas.orders import (
    AdminOrderResponse,
    AdminRequestDetailResponse,
    AdminRequestStatusResponse,
    AdminRequestUser,
    AdminWorkerRef,
    NotificationResponse,
    OrderResponse,
    OrderWorkerChange,
    OrderWorkerResponse,
    RequestResponse,
    RequestStatusUpdate,
    ReviewResponse,
    StatusResponse,
)
from app.schemas.users import (
    AdminUserDetailResponse,
    AdminUserResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
    SkillCreate,
    SkillResponse,
    UserUpdate,
    WorkerCreate,
    WorkerDetailResponse,
    WorkerSummary,
    WorkerUpdate,
    WorkerUserInfo,
)
from app.services import catalog as catalog_service
from app.services import orders as order_service
from app.services import users as user_service
from app.services.orders import (
    InvalidOrderState,
    NotOrderWorker,
    OrderNotFound,
    StatusNotFound,
)
from app.services.orders import WorkerNotFound as OrderWorkerNotFound
from app.services.catalog import (
    InvalidQuantity,
    SparePartNotFound,
    StreetNotFound,
    WarehouseNotFound,
    WarehouseStockConflict,
    WarehouseStockNotFound,
)
from app.services.users import (
    InvalidSchedule,
    ScheduleNotFound,
    SkillNotFound,
    TechnicNotFound,
    UserAlreadyExists,
    WorkerEmailConflict,
    WorkerNotFound,
)

router = APIRouter(prefix="/control", tags=[TAG_ADMIN])


# ---------------------------------------------------------------------------
# Сериализаторы (без изменения схемы БД)
# ---------------------------------------------------------------------------
def _serialize_admin_user(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        is_admin=bool(user.is_admin),
        worker_id=user.worker_profile.id if user.worker_profile else None,
    )


def _serialize_admin_order(order: Order) -> AdminOrderResponse:
    base = OrderResponse.model_validate(order).model_dump()
    workers = [
        AdminWorkerRef(
            id=ow.worker.id,
            user_id=ow.worker.user_id,
            full_name=ow.worker.user.full_name if ow.worker.user else None,
        )
        for ow in order.workers
    ]
    return AdminOrderResponse(**base, workers=workers)


def _serialize_admin_request(request: Request) -> AdminRequestDetailResponse:
    base = RequestResponse.model_validate(request).model_dump(exclude={"orders"})
    return AdminRequestDetailResponse(
        **base,
        user=(
            AdminRequestUser.model_validate(request.user)
            if request.user is not None
            else None
        ),
        orders=[_serialize_admin_order(o) for o in request.orders],
    )


def _serialize_worker_summary(worker: Worker) -> WorkerSummary:
    user = worker.user
    return WorkerSummary(
        id=worker.id,
        user_id=worker.user_id,
        full_name=user.full_name if user else None,
        email=user.email if user else None,
        phone=user.phone if user else None,
        experience=worker.experience,
        latitude=worker.latitude,
        longitude=worker.longitude,
    )


def _serialize_worker_detail(worker: Worker, workload: int) -> WorkerDetailResponse:
    from app.schemas.orders import OrderSummary

    return WorkerDetailResponse(
        id=worker.id,
        user_id=worker.user_id,
        experience=worker.experience,
        latitude=worker.latitude,
        longitude=worker.longitude,
        user=WorkerUserInfo.model_validate(worker.user) if worker.user else None,
        skills=[SkillResponse.model_validate(s) for s in worker.skills],
        schedules=[ScheduleResponse.model_validate(s) for s in worker.schedules],
        orders=[OrderSummary.model_validate(ow.order) for ow in worker.orders],
        workload=workload,
    )


def _serialize_review(order: Order) -> ReviewResponse:
    request = order.request
    user = request.user if request is not None else None
    return ReviewResponse(
        order_id=order.id,
        request_id=order.request_id,
        user_id=request.user_id if request is not None else None,
        user_full_name=user.full_name if user else None,
        client_review=order.client_review or "",
        total_amount=order.total_amount,
        work_description=order.work_description,
        work_end_time=order.work_end_time,
    )


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------
@router.get(
    "/users",
    response_model=list[AdminUserResponse],
    summary="Список всех пользователей",
)
async def list_users(
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список всех пользователей (user/worker/admin). Только для админа.

    Возвращает id, ФИО, email, телефон, признак администратора и ID профиля
    работника при наличии. Пароли в ответ не попадают.
    """
    users = await user_service.list_users(session)
    return [_serialize_admin_user(u) for u in users]


@router.get(
    "/users/{user_id}",
    response_model=AdminUserDetailResponse,
    summary="Пользователь по ID",
)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Подробная информация о пользователе по ID (включая профиль работника)."""
    user = await user_service.get_user_detail(session, user_id)
    if user is None:
        raise _not_found("User not found")
    return _serialize_admin_user(user)


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserDetailResponse,
    summary="Изменить пользователя",
)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменение разрешённых данных пользователя: ФИО, email, телефон.

    Пароль и флаг администратора через этот эндпоинт изменить нельзя.
    Несуществующий пользователь -> 404, занятый email -> 409.
    """
    user = await user_service.get_user_detail(session, user_id)
    if user is None:
        raise _not_found("User not found")
    try:
        await user_service.update_user(
            session,
            user=user,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
        )
    except UserAlreadyExists:
        raise _conflict("Email already registered")
    updated = await user_service.get_user_detail(session, user_id)
    return _serialize_admin_user(updated)


# ---------------------------------------------------------------------------
# Работники
# ---------------------------------------------------------------------------
@router.get(
    "/workers",
    response_model=list[WorkerSummary],
    summary="Список всех работников",
)
async def list_workers(
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список всех работников с данными связанного пользователя."""
    workers = await user_service.list_workers(session)
    return [_serialize_worker_summary(w) for w in workers]


@router.post(
    "/workers",
    response_model=WorkerSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Создать работника",
)
async def create_worker(
    payload: WorkerCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создаёт нового работника вместе с новым профилем пользователя.

    User и Worker создаются в одной транзакции; при ошибке (например, занятый
    email) операция полностью откатывается. Пароль хешируется. Занятый email
    -> 409.
    """
    try:
        worker = await user_service.create_worker_with_user(
            session,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            phone=payload.phone,
            experience=payload.experience,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    except (WorkerEmailConflict, UserAlreadyExists):
        raise _conflict("Email already registered")
    worker = await user_service.get_worker_detail(session, worker.id)
    return _serialize_worker_summary(worker)


@router.get(
    "/workers/{worker_id}",
    response_model=WorkerDetailResponse,
    summary="Работник по ID",
)
async def get_worker(
    worker_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Профиль работника: пользователь, навыки, техника, расписание, заказы.

    ``workload`` — число активных (незавершённых) заказов; рассчитывается
    сервисом из существующих данных OrderWorker/Order/Status.
    """
    worker = await user_service.get_worker_detail(session, worker_id)
    if worker is None:
        raise _not_found("Worker not found")
    workload = await user_service.count_worker_active_orders(session, worker_id)
    return _serialize_worker_detail(worker, workload)


@router.patch(
    "/workers/{worker_id}",
    response_model=WorkerSummary,
    summary="Изменить работника",
)
async def update_worker(
    worker_id: int,
    payload: WorkerUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменение профиля работника: опыт и координаты."""
    worker = await user_service.get_worker_by_id(session, worker_id)
    if worker is None:
        raise _not_found("Worker not found")
    await user_service.update_worker(
        session,
        worker=worker,
        experience=payload.experience,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    worker = await user_service.get_worker_detail(session, worker_id)
    return _serialize_worker_summary(worker)


# ---------------------------------------------------------------------------
# Навыки работника
# ---------------------------------------------------------------------------
@router.get(
    "/workers/{worker_id}/skills",
    response_model=list[SkillResponse],
    summary="Навыки работника",
)
async def list_worker_skills(
    worker_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список навыков работника (с раскрытой техникой)."""
    worker = await user_service.get_worker_by_id(session, worker_id)
    if worker is None:
        raise _not_found("Worker not found")
    return await user_service.list_worker_skills(session, worker_id)


@router.post(
    "/workers/{worker_id}/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить навык работнику",
)
async def add_worker_skill(
    worker_id: int,
    payload: SkillCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Добавляет навык (связь работник–техника).

    Работник и (при указании) техника должны существовать. Повторное
    добавление той же связи не создаёт дубликат — возвращается существующая.
    """
    try:
        return await user_service.add_worker_skill(
            session, worker_id=worker_id, technic_id=payload.technic_id
        )
    except WorkerNotFound:
        raise _not_found("Worker not found")
    except TechnicNotFound:
        raise _not_found("Technic not found")


@router.delete(
    "/workers/{worker_id}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить навык работника",
)
async def delete_worker_skill(
    worker_id: int,
    skill_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Удаляет навык работника. Отсутствующий навык -> 404."""
    try:
        await user_service.delete_worker_skill(
            session, worker_id=worker_id, skill_id=skill_id
        )
    except SkillNotFound:
        raise _not_found("Skill not found")


# ---------------------------------------------------------------------------
# Расписание работника
# ---------------------------------------------------------------------------
@router.get(
    "/workers/{worker_id}/schedules",
    response_model=list[ScheduleResponse],
    summary="Расписание работника",
)
async def list_worker_schedules(
    worker_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Записи расписания работника (интервалы времени и связанные заказы)."""
    worker = await user_service.get_worker_by_id(session, worker_id)
    if worker is None:
        raise _not_found("Worker not found")
    return await user_service.list_worker_schedules(session, worker_id)


@router.post(
    "/workers/{worker_id}/schedules",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить запись расписания",
)
async def create_worker_schedule(
    worker_id: int,
    payload: ScheduleCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создаёт интервал расписания. Проверяются работник, интервал и заказ."""
    try:
        return await user_service.create_schedule(
            session,
            worker_id=worker_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
            order_id=payload.order_id,
        )
    except WorkerNotFound:
        raise _not_found("Worker not found")
    except InvalidSchedule as exc:
        raise _bad_request(str(exc))


@router.patch(
    "/workers/{worker_id}/schedules/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Изменить запись расписания",
)
async def update_worker_schedule(
    worker_id: int,
    schedule_id: int,
    payload: ScheduleUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменяет интервал/заказ записи расписания. Некорректный интервал -> 400."""
    try:
        return await user_service.update_schedule(
            session,
            schedule_id=schedule_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
            order_id=payload.order_id,
            order_id_provided="order_id" in payload.model_fields_set,
        )
    except ScheduleNotFound:
        raise _not_found("Schedule not found")
    except InvalidSchedule as exc:
        raise _bad_request(str(exc))


@router.delete(
    "/workers/{worker_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить запись расписания",
)
async def delete_worker_schedule(
    worker_id: int,
    schedule_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Удаляет запись расписания. Отсутствующая запись -> 404."""
    try:
        await user_service.delete_schedule(session, schedule_id=schedule_id)
    except ScheduleNotFound:
        raise _not_found("Schedule not found")


# ---------------------------------------------------------------------------
# Заявки
# ---------------------------------------------------------------------------
@router.get(
    "/requests",
    response_model=list[AdminRequestDetailResponse],
    summary="Список всех заявок",
)
async def list_requests(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Фильтр по имени статуса заявки из справочника Status",
    ),
    user_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID пользователя-владельца"
    ),
    worker_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID работника, назначенного на заказ"
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Размер страницы"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список всех заявок независимо от владельца.

    Фильтры комбинируются: статус, пользователь, работник. Сортировка — по ID.
    """
    requests = await order_service.list_admin_requests(
        session,
        status=status_filter,
        user_id=user_id,
        worker_id=worker_id,
        limit=limit,
        offset=offset,
    )
    return [_serialize_admin_request(r) for r in requests]


@router.get(
    "/requests/{request_id}",
    response_model=AdminRequestDetailResponse,
    summary="Заявка по ID",
)
async def get_request(
    request_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Полная информация о заявке: владелец, адрес, заказы и работники."""
    request = await order_service.get_admin_request(session, request_id)
    if request is None:
        raise _not_found("Request not found")
    return _serialize_admin_request(request)


@router.patch(
    "/requests/{request_id}/status",
    response_model=AdminRequestStatusResponse,
    summary="Изменить статус заявки",
)
async def change_request_status(
    request_id: int,
    payload: RequestStatusUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Администратор вручную задаёт существующий статус заявки.

    Статус выбирается из справочника ``Status`` (``status_id`` или
    ``status_name``). Новая система статусов не создаётся. При переводе заявки
    в статус отмены (``CANCELLED``/``CANCELED``) формируется уведомление
    владельцу — оно возвращается в поле ``notification`` (реальная система
    уведомлений не подключена, отдельная таблица не создаётся).

    Несуществующая заявка или статус -> 404; отсутствие параметров статуса ->
    409.
    """
    try:
        request, notification = await order_service.admin_set_request_status(
            session,
            request_id=request_id,
            status_id=payload.status_id,
            status_name=payload.status_name,
        )
    except OrderNotFound:
        raise _not_found("Request not found")
    except StatusNotFound:
        raise _not_found("Status not found")
    except InvalidOrderState:
        raise _conflict("status_id or status_name is required")

    base = _serialize_admin_request(request)
    return AdminRequestStatusResponse(
        **base.model_dump(),
        notification=(
            NotificationResponse(**notification) if notification else None
        ),
    )


@router.get(
    "/statuses",
    response_model=list[StatusResponse],
    summary="Справочник статусов",
)
async def list_statuses(
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Существующий справочник статусов заявок/заказов для выбора админом."""
    statuses = await order_service.list_statuses(session)
    return [StatusResponse.model_validate(s) for s in statuses]


# ---------------------------------------------------------------------------
# Заказы и контроль выполнения
# ---------------------------------------------------------------------------
@router.get(
    "/orders",
    response_model=list[AdminOrderResponse],
    summary="Список всех заказов",
)
async def list_orders(
    worker_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID назначенного работника"
    ),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Фильтр по имени статуса заказа из справочника Status",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Размер страницы"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Список заказов с назначенными работниками (для контроля выполнения)."""
    orders = await order_service.list_admin_orders(
        session, worker_id=worker_id, status=status_filter, limit=limit, offset=offset
    )
    return [_serialize_admin_order(o) for o in orders]


@router.get(
    "/orders/{order_id}",
    response_model=AdminOrderResponse,
    summary="Заказ по ID",
)
async def get_order(
    order_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Данные заказа: заявка, работники, статус, чек-лист, отчёт, запчасти,
    фотографии, стоимость и отзыв клиента (если оставлен).
    """
    order = await order_service.get_admin_order(session, order_id)
    if order is None:
        raise _not_found("Order not found")
    return _serialize_admin_order(order)


@router.put(
    "/orders/{order_id}/worker",
    response_model=OrderWorkerResponse,
    summary="Назначить/заменить работника заказа",
)
async def change_order_worker(
    order_id: int,
    payload: OrderWorkerChange,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Назначает или заменяет работника, привязанного к заказу.

    Используется существующая связь ``OrderWorker`` (новая таблица/поле не
    создаются). При ``replace_existing=true`` текущие работники заказа
    заменяются указанным; при ``false`` работник добавляется дополнительно.
    Расписание и прочие связанные данные не изменяются.
    """
    try:
        order = await order_service.change_order_worker(
            session,
            order_id=order_id,
            worker_id=payload.worker_id,
            replace_existing=payload.replace_existing,
        )
    except OrderNotFound:
        raise _not_found("Order not found")
    except OrderWorkerNotFound:
        raise _not_found("Worker not found")
    return _serialize_admin_order(order)


@router.delete(
    "/orders/{order_id}/worker/{worker_id}",
    response_model=OrderWorkerResponse,
    summary="Удалить работника из заказа",
)
async def remove_order_worker(
    order_id: int,
    worker_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Удаляет работника из заказа (существующая связь ``OrderWorker``).

    Несуществующий заказ -> 404; работник не привязан к заказу -> 404.
    """
    try:
        order = await order_service.remove_order_worker(
            session, order_id=order_id, worker_id=worker_id
        )
    except OrderNotFound:
        raise _not_found("Order not found")
    except NotOrderWorker:
        raise _not_found("Worker is not assigned to this order")
    return _serialize_admin_order(order)


# ---------------------------------------------------------------------------
# Отзывы
# ---------------------------------------------------------------------------
@router.get(
    "/reviews",
    response_model=list[ReviewResponse],
    summary="Список отзывов клиентов",
)
async def list_reviews(
    user_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID пользователя-владельца заявки"
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Размер страницы"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Отзывы клиентов (``Order.client_review``). Заказы без отзыва исключены."""
    orders = await order_service.list_reviews(
        session, user_id=user_id, limit=limit, offset=offset
    )
    return [_serialize_review(o) for o in orders]


@router.get(
    "/reviews/{order_id}",
    response_model=ReviewResponse,
    summary="Отзыв по ID заказа",
)
async def get_review(
    order_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Отзыв по конкретному заказу. Если отзыва нет -> 404."""
    order = await order_service.get_review(session, order_id)
    if order is None:
        raise _not_found("Review not found")
    return _serialize_review(order)


# ---------------------------------------------------------------------------
# Справочник: техника
# ---------------------------------------------------------------------------
@router.get(
    "/technics/{technic_id}",
    response_model=TechnicResponse,
    summary="Техника по ID",
)
async def get_technic(
    technic_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Техника по ID. Отсутствующая запись -> 404."""
    technic = await catalog_service.get_technic(session, technic_id)
    if technic is None:
        raise _not_found("Technic not found")
    return technic


@router.post(
    "/technics",
    response_model=TechnicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать технику",
)
async def create_technic(
    payload: TechnicCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создание записи техники (name, model_params)."""
    return await catalog_service.create_technic(
        session, name=payload.name, model_params=payload.model_params
    )


@router.patch(
    "/technics/{technic_id}",
    response_model=TechnicResponse,
    summary="Изменить технику",
)
async def update_technic(
    technic_id: int,
    payload: TechnicUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменение техники. Отсутствующая запись -> 404."""
    technic = await catalog_service.get_technic(session, technic_id)
    if technic is None:
        raise _not_found("Technic not found")
    return await catalog_service.update_technic(
        session,
        technic=technic,
        name=payload.name,
        model_params=payload.model_params,
    )


# ---------------------------------------------------------------------------
# Справочник: запчасти
# ---------------------------------------------------------------------------
@router.get(
    "/spare-parts/{spare_part_id}",
    response_model=SparePartResponse,
    summary="Запчасть по ID",
)
async def get_spare_part(
    spare_part_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Запчасть по ID. Отсутствующая запись -> 404."""
    spare_part = await catalog_service.get_spare_part(session, spare_part_id)
    if spare_part is None:
        raise _not_found("Spare part not found")
    return spare_part


@router.post(
    "/spare-parts",
    response_model=SparePartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать запчасть",
)
async def create_spare_part(
    payload: SparePartCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создание записи запчасти (name, description, price)."""
    return await catalog_service.create_spare_part(
        session,
        name=payload.name,
        description=payload.description,
        price=payload.price,
    )


@router.patch(
    "/spare-parts/{spare_part_id}",
    response_model=SparePartResponse,
    summary="Изменить запчасть",
)
async def update_spare_part(
    spare_part_id: int,
    payload: SparePartUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменение запчасти. Отсутствующая запись -> 404."""
    spare_part = await catalog_service.get_spare_part(session, spare_part_id)
    if spare_part is None:
        raise _not_found("Spare part not found")
    return await catalog_service.update_spare_part(
        session,
        spare_part=spare_part,
        name=payload.name,
        description=payload.description,
        price=payload.price,
    )


# ---------------------------------------------------------------------------
# Справочник: склады
# ---------------------------------------------------------------------------
@router.get(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    summary="Склад по ID",
)
async def get_warehouse(
    warehouse_id: int,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Склад по ID. Отсутствующая запись -> 404."""
    warehouse = await catalog_service.get_warehouse(session, warehouse_id)
    if warehouse is None:
        raise _not_found("Warehouse not found")
    return warehouse


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать склад",
)
async def create_warehouse(
    payload: WarehouseCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создание склада (name, street_id, house_number). Несуществующая улица -> 404."""
    try:
        return await catalog_service.create_warehouse(
            session,
            name=payload.name,
            street_id=payload.street_id,
            house_number=payload.house_number,
        )
    except StreetNotFound:
        raise _not_found("Street not found")


@router.patch(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    summary="Изменить склад",
)
async def update_warehouse(
    warehouse_id: int,
    payload: WarehouseUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменение склада. Отсутствующий склад/улица -> 404."""
    warehouse = await catalog_service.get_warehouse(session, warehouse_id)
    if warehouse is None:
        raise _not_found("Warehouse not found")
    try:
        return await catalog_service.update_warehouse(
            session,
            warehouse=warehouse,
            name=payload.name,
            street_id=payload.street_id,
            house_number=payload.house_number,
        )
    except StreetNotFound:
        raise _not_found("Street not found")


# ---------------------------------------------------------------------------
# Складские остатки
# ---------------------------------------------------------------------------
@router.get(
    "/warehouse-stocks",
    response_model=list[WarehouseStockDetailResponse],
    summary="Складские остатки",
)
async def list_warehouse_stocks(
    warehouse_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID склада"
    ),
    spare_part_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID запчасти"
    ),
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Остатки по всем складам с раскрытыми запчастью и складом.

    Складского учёта (списаний/приходов) нет — отображаются записи остатков.
    """
    stocks = await catalog_service.list_warehouse_stocks(
        session, warehouse_id=warehouse_id, spare_part_id=spare_part_id
    )
    return [_to_stock_detail(s) for s in stocks]


@router.get(
    "/warehouses/{warehouse_id}/stocks",
    response_model=list[WarehouseStockDetailResponse],
    summary="Остатки конкретного склада",
)
async def list_warehouse_stocks_by_warehouse(
    warehouse_id: int,
    spare_part_id: int | None = Query(
        default=None, ge=1, description="Фильтр по ID запчасти"
    ),
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Остатки конкретного склада (с опциональным фильтром по запчасти)."""
    warehouse = await catalog_service.get_warehouse(session, warehouse_id)
    if warehouse is None:
        raise _not_found("Warehouse not found")
    stocks = await catalog_service.list_warehouse_stocks(
        session, warehouse_id=warehouse_id, spare_part_id=spare_part_id
    )
    return [_to_stock_detail(s) for s in stocks]


@router.post(
    "/warehouse-stocks",
    response_model=WarehouseStockDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить складской остаток",
)
async def create_warehouse_stock(
    payload: WarehouseStockCreate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Создаёт запись остатка. Проверяются склад, запчасть и количество.

    Повторная запись для пары (warehouse_id, spare_part_id) -> 409.
    """
    try:
        stock = await catalog_service.create_warehouse_stock(
            session,
            warehouse_id=payload.warehouse_id,
            spare_part_id=payload.spare_part_id,
            quantity=payload.quantity,
        )
    except WarehouseNotFound:
        raise _not_found("Warehouse not found")
    except SparePartNotFound:
        raise _not_found("Spare part not found")
    except InvalidQuantity as exc:
        raise _bad_request(f"Invalid quantity: {exc}")
    except WarehouseStockConflict:
        raise _conflict(
            "Stock for this warehouse and spare part already exists; update it"
        )
    return _to_stock_detail(stock)


@router.patch(
    "/warehouse-stocks/{stock_id}",
    response_model=WarehouseStockDetailResponse,
    summary="Изменить количество остатка",
)
async def update_warehouse_stock(
    stock_id: int,
    payload: WarehouseStockUpdate,
    current_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
):
    """Изменяет количество остатка. Отсутствующий остаток -> 404."""
    stock = await catalog_service.get_warehouse_stock(session, stock_id)
    if stock is None:
        raise _not_found("Warehouse stock not found")
    try:
        stock = await catalog_service.update_warehouse_stock(
            session, stock=stock, quantity=payload.quantity
        )
    except InvalidQuantity as exc:
        raise _bad_request(f"Invalid quantity: {exc}")
    return _to_stock_detail(stock)


def _to_stock_detail(stock: WarehouseStock) -> WarehouseStockDetailResponse:
    return WarehouseStockDetailResponse(
        id=stock.id,
        warehouse_id=stock.warehouse_id,
        spare_part_id=stock.spare_part_id,
        quantity=stock.quantity,
        spare_part=(
            SparePartResponse.model_validate(stock.spare_part)
            if stock.spare_part
            else None
        ),
        warehouse=(
            WarehouseResponse.model_validate(stock.warehouse)
            if stock.warehouse
            else None
        ),
    )