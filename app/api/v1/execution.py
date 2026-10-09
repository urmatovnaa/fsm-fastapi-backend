from fastapi import APIRouter, HTTPException, status

from app.models.users import UserRole
from app.schemas.orders import RequestCreate, RequestResponse, WorkOrderResponse
from app.services import orders as order_service
from app.services import users as user_service
from app.services.orders import (
    InvalidOrderState,
    NotOrderOwner,
    OrderNotFound,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "/requests",
    response_model=RequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_request(
    payload: RequestCreate,
    user_id: int,
    # TODO: заменить на Depends(get_current_user)
):
    request = order_service.create_request(user_id=user_id, data=payload)
    return request


@router.post(
    "/requests/{request_id}/accept",
    response_model=WorkOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_request(
    request_id: int,
    worker_id: int,
    # TODO: заменить на Depends(get_current_user)
):
    worker = await user_service.get_user_by_id(worker_id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="worker not found",
        )

    if worker.role != UserRole.WORKER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only WORKER can accept requests",
        )

    try:
        work_order = order_service.accept_request(
            request_id=request_id,
            worker_id=worker_id,
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

    return work_order


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=WorkOrderResponse,
)
async def complete_work_order(
    work_order_id: int,
    worker_id: int,
    # TODO: заменить на Depends(get_current_user)
):
    try:
        work_order = order_service.complete_work_order(
            work_order_id=work_order_id,
            worker_id=worker_id,
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

    return work_order