"""API работника (мастера).

Доступно пользователям с профилем мастера (``Worker``). Мастер видит и
изменяет только заказы, назначенные лично ему: принятие заявки, начало
работы, отчёт, запчасти, фотографии результата, завершение/невыполнение/
отмену. Принадлежность и допустимость переходов проверяются в сервисном слое.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.execution import require_worker, run_order_action
from app.core.database import get_db
from app.core.tags import TAG_WORKER
from app.models.users import User
from app.schemas.orders import (
    OrderPartCreate,
    OrderPhotoCreate,
    OrderReportUpdate,
    OrderResponse,
)
from app.services import orders as order_service

router = APIRouter(prefix="/orders", tags=[TAG_WORKER])


@router.get(
    "/work-orders",
    response_model=list[OrderResponse],
    summary="Мои заказы",
)
async def list_work_orders(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Список заказов, назначенных текущему мастеру (только его заказы)."""
    worker = await require_worker(session, current_user)
    return await order_service.list_orders(session, worker_id=worker.id)


@router.get(
    "/work-orders/history",
    response_model=list[OrderResponse],
    summary="История моих заказов",
)
async def list_work_order_history(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Фильтр по терминальному статусу заказа",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """История заказов мастера: завершённые, отменённые, невыполненные."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.list_order_history(
            session,
            worker_id=worker.id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    )


@router.post(
    "/requests/{request_id}/accept",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Принять заявку (создать заказ)",
)
async def accept_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Мастер принимает заявку: создаётся заказ ``ACCEPTED``, заявка -> ``COMPLETED``."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.accept_request(
            session, request_id=request_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/en-route",
    response_model=OrderResponse,
    summary="Выехал к клиенту",
)
async def start_route(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """``ACCEPTED`` -> ``EN_ROUTE``."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.start_route(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/start",
    response_model=OrderResponse,
    summary="Начать работу",
)
async def start_work(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """``EN_ROUTE`` -> ``IN_PROGRESS``, устанавливает ``work_start_time``."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.start_work(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.put(
    "/work-orders/{work_order_id}/report",
    response_model=OrderResponse,
    summary="Отчёт о выполненной работе",
)
async def update_report(
    work_order_id: int,
    payload: OrderReportUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Заполнение/обновление чек-листа, описания работ и итоговой стоимости."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.update_report(
            session,
            order_id=work_order_id,
            worker_id=worker.id,
            checklist=payload.checklist,
            work_description=payload.work_description,
            total_amount=payload.total_amount,
        )
    )


@router.post(
    "/work-orders/{work_order_id}/parts",
    response_model=OrderResponse,
    summary="Добавить использованную запчасть",
)
async def add_order_part(
    work_order_id: int,
    payload: OrderPartCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Фиксация использованной запчасти (складского учёта нет)."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.add_order_part(
            session,
            order_id=work_order_id,
            worker_id=worker.id,
            data=payload,
        )
    )


@router.post(
    "/work-orders/{work_order_id}/photos",
    response_model=OrderResponse,
    summary="Добавить фотографию результата",
)
async def add_order_photo(
    work_order_id: int,
    payload: OrderPhotoCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Добавление фотографии, связанной с заказом (модель ``OrderPhoto``)."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.add_order_photo(
            session,
            order_id=work_order_id,
            worker_id=worker.id,
            data=payload,
        )
    )


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=OrderResponse,
    summary="Завершить заказ",
)
async def complete_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """``IN_PROGRESS`` -> ``COMPLETED``, устанавливает ``work_end_time``.

    Статус заявки повторно не меняется — она уже ``COMPLETED``.
    """
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.complete_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/not-completed",
    response_model=OrderResponse,
    summary="Работа не выполнена",
)
async def not_completed_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """``ACCEPTED``/``EN_ROUTE``/``IN_PROGRESS`` -> ``NOT_COMPLETED``."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.not_completed_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/cancel",
    response_model=OrderResponse,
    summary="Отменить заказ",
)
async def cancel_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """``ACCEPTED``/``EN_ROUTE`` -> ``CANCELLED``."""
    worker = await require_worker(session, current_user)
    return await run_order_action(
        order_service.cancel_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )