from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.users import User, Worker
from app.schemas.orders import OrderResponse, RequestCreate, RequestResponse
from app.services import orders as order_service
from app.services import users as user_service
from app.services.orders import (
    InvalidOrderState,
    NotOrderOwner,
    OrderNotFound,
    StatusNotFound,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


async def _require_worker(session: AsyncSession, current_user: User) -> Worker:
    """Возвращает профиль мастера или 403, если его нет."""
    worker = await user_service.get_worker_by_user_id(session, current_user.id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user has no worker profile",
        )
    return worker


def _status_seed_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Statuses not seeded. Run seed.",
    )


# ---------------------------------------------------------------------------
# Заявки
# ---------------------------------------------------------------------------
@router.post(
    "/requests",
    response_model=RequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_request(
    payload: RequestCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        request = await order_service.create_request(
            session,
            user_id=current_user.id,
            data=payload,
        )
    except StatusNotFound:
        raise _status_seed_error()
    return request


@router.get("/requests", response_model=list[RequestResponse])
async def list_requests(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await order_service.list_requests(session)


@router.get("/requests/{request_id}", response_model=RequestResponse)
async def get_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    request = await order_service.get_request(session, request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    return request


@router.post(
    "/requests/{request_id}/accept",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)

    try:
        order = await order_service.accept_request(
            session,
            request_id=request_id,
            worker_id=worker.id,
        )
    except OrderNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidOrderState:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request is not available for acceptance",
        )
    except StatusNotFound:
        raise _status_seed_error()

    return order


@router.post(
    "/requests/{request_id}/reject",
    response_model=RequestResponse,
)
async def reject_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await order_service.reject_request(session, request_id=request_id)
    except OrderNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidOrderState:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request cannot be rejected from its current state",
        )
    except StatusNotFound:
        raise _status_seed_error()


@router.post(
    "/requests/{request_id}/cancel",
    response_model=RequestResponse,
)
async def cancel_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await order_service.cancel_request(session, request_id=request_id)
    except OrderNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidOrderState:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request cannot be cancelled from its current state",
        )
    except StatusNotFound:
        raise _status_seed_error()


# ---------------------------------------------------------------------------
# Заказы (наряды мастера)
# ---------------------------------------------------------------------------
@router.get("/work-orders", response_model=list[OrderResponse])
async def list_work_orders(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await order_service.list_orders(session, worker_id=worker.id)


async def _run_order_action(coro):
    """Общий маппинг доменных исключений заказов в HTTP-ответы."""
    try:
        return await coro
    except OrderNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Work order not found",
        )
    except NotOrderOwner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Work order belongs to another worker",
        )
    except InvalidOrderState:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid order status transition",
        )
    except StatusNotFound:
        raise _status_seed_error()


@router.post("/work-orders/{work_order_id}/en-route", response_model=OrderResponse)
async def start_route(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await _run_order_action(
        order_service.start_route(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post("/work-orders/{work_order_id}/start", response_model=OrderResponse)
async def start_work(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await _run_order_action(
        order_service.start_work(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=OrderResponse,
)
async def complete_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await _run_order_action(
        order_service.complete_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post(
    "/work-orders/{work_order_id}/not-completed",
    response_model=OrderResponse,
)
async def not_completed_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await _run_order_action(
        order_service.not_completed_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )


@router.post("/work-orders/{work_order_id}/cancel", response_model=OrderResponse)
async def cancel_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await _require_worker(session, current_user)
    return await _run_order_action(
        order_service.cancel_order(
            session, order_id=work_order_id, worker_id=worker.id
        )
    )