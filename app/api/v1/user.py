"""API пользователя (клиента).

Доступно любому авторизованному пользователю. Пользователь работает только
со своими заявками: создаёт их, просматривает, отслеживает связанный заказ,
смотрит результат работы и оставляет отзыв по завершённому заказу.

Проверки владения выполняются в сервисном слое
(``app/services/orders.py``), а не только фильтрацией в API.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.execution import run_order_action
from app.core.database import get_db
from app.core.tags import TAG_USER
from app.models.users import User
from app.schemas.orders import (
    ClientReviewCreate,
    OrderResponse,
    RequestCreate,
    RequestDetailResponse,
    RequestResponse,
    RequestTechnicAdd,
)
from app.services import orders as order_service
from app.services.orders import (
    InvalidOrderState,
    NotOrderOwner,
    OrderAlreadyCreated,
    OrderNotFound,
    TechnicNotFound,
)

router = APIRouter(prefix="/orders", tags=[TAG_USER])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Request not found",
    )


def _conflict(detail: str = "Invalid request state") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


@router.post(
    "/requests",
    response_model=RequestDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заявку",
)
async def create_request(
    payload: RequestCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Создаёт заявку от имени текущего пользователя.

    Статус заявки всегда ``SEARCHING_MASTER``. ``user_id`` берётся из токена —
    создать заявку от имени другого пользователя нельзя. Можно сразу указать
    одну или несколько единиц техники (``technic_ids``) — они сохраняются
    через существующую связь ``RequestTechnic``.
    """
    return await run_order_action(
        order_service.create_request(
            session, user_id=current_user.id, data=payload
        )
    )


@router.get(
    "/requests",
    response_model=list[RequestDetailResponse],
    summary="Список своих заявок",
)
async def list_requests(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Возвращает только заявки текущего пользователя (с составом техники)."""
    return await order_service.list_requests(session, user_id=current_user.id)


@router.post(
    "/requests/{request_id}/technics",
    response_model=RequestDetailResponse,
    summary="Добавить технику к заявке",
)
async def add_request_technics(
    request_id: int,
    payload: RequestTechnicAdd,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Добавляет/меняет технику существующей заявки пользователя.

    Разрешено, только пока по заявке не создан заказ (работник не назначен,
    статус заявки ``SEARCHING_MASTER``): состав техники заявки заменяется на
    переданный, новый заказ не создаётся (сценарий А).

    Если заказ уже создан — изменение запрещено (409), заявка не меняется и
    новый заказ не создаётся (сценарий Б).
    """
    try:
        return await order_service.add_request_technics(
            session,
            request_id=request_id,
            user_id=current_user.id,
            technic_ids=payload.technic_ids,
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()
    except OrderAlreadyCreated:
        raise _conflict(
            "Заказ уже создан. Добавить технику к текущей заявке невозможно. "
            "Создайте новую заявку с необходимой техникой."
        )
    except TechnicNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technic not found",
        )


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetailResponse,
    summary="Детали своей заявки",
)
async def get_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Детали только собственной заявки (со связанными заказами)."""
    try:
        return await order_service.get_user_request(
            session, request_id=request_id, user_id=current_user.id
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        # Не раскрываем существование чужой заявки.
        raise _not_found()


@router.post(
    "/requests/{request_id}/reject",
    response_model=RequestResponse,
    summary="Отклонить свою заявку",
)
async def reject_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Отклонение собственной заявки (``SEARCHING_MASTER`` -> ``REJECTED``)."""
    try:
        return await order_service.reject_request(
            session, request_id=request_id, user_id=current_user.id
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()
    except InvalidOrderState:
        raise _conflict("Request cannot be rejected from its current state")


@router.post(
    "/requests/{request_id}/cancel",
    response_model=RequestResponse,
    summary="Отменить свою заявку",
)
async def cancel_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Отмена собственной заявки (``SEARCHING_MASTER`` -> ``CANCELLED``)."""
    try:
        return await order_service.cancel_request(
            session, request_id=request_id, user_id=current_user.id
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()
    except InvalidOrderState:
        raise _conflict("Request cannot be cancelled from its current state")


@router.get(
    "/requests/{request_id}/orders",
    response_model=list[OrderResponse],
    summary="Заказы по своей заявке",
)
async def list_request_orders(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Все заказы, созданные по заявке пользователя (отслеживание процесса)."""
    try:
        return await order_service.list_user_orders(
            session, request_id=request_id, user_id=current_user.id
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()


@router.get(
    "/requests/{request_id}/result",
    response_model=OrderResponse,
    summary="Результат работы по своей заявке",
)
async def get_request_result(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Результат работы (отчёт, запчасти, фото) по своей заявке.

    Если заказ ещё не создан или отчёт не заполнен — поля возвращаются
    пустыми согласно текущим соглашениям API.
    """
    try:
        order = await order_service.get_request_result(
            session, request_id=request_id, user_id=current_user.id
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request has no order yet",
        )
    return order


@router.post(
    "/requests/{request_id}/review",
    response_model=OrderResponse,
    summary="Оставить отзыв о выполненной работе",
)
async def add_review(
    request_id: int,
    payload: ClientReviewCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Отзыв по завершённому (``COMPLETED``) заказу своей заявки.

    Отзыв недоступен для заказов со статусами ``NOT_COMPLETED``/``CANCELLED``
    или любыми незавершёнными. Повторный отзыв запрещён.
    """
    try:
        return await order_service.add_client_review(
            session,
            request_id=request_id,
            user_id=current_user.id,
            review=payload.client_review,
        )
    except OrderNotFound:
        raise _not_found()
    except NotOrderOwner:
        raise _not_found()
    except InvalidOrderState:
        raise _conflict(
            "Review is only allowed for a completed order that has no review yet"
        )