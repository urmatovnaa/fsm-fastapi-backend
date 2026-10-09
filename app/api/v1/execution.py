from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.constants import RoleNames
from app.core.database import get_db
from app.models.users import User
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Statuses not seeded. Run seed.",
        )
    return request


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
    role_name = current_user.role.name if current_user.role else None
    if role_name != RoleNames.WORKER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only WORKER can accept requests",
        )

    worker = await user_service.get_worker_by_user_id(session, current_user.id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found",
        )

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
            detail="Request is not in NEW state",
        )
    except StatusNotFound:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Statuses not seeded. Run seed.",
        )

    return order


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=OrderResponse,
)
async def complete_work_order(
    work_order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    worker = await user_service.get_worker_by_user_id(session, current_user.id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user is not a worker",
        )

    try:
        order = await order_service.complete_order(
            session,
            order_id=work_order_id,
            worker_id=worker.id,
        )
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
            detail="Request is not in ASSIGNED state",
        )
    except StatusNotFound:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Statuses not seeded. Run seed.",
        )

    return order