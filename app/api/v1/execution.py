"""Общие helpers для роутеров заявок/заказов.

Раньше этот модуль содержал весь execution-роутер. Теперь endpoints разнесены
по ролям (``user.py`` — User / Client, ``worker.py`` — Worker / Master), а здесь
остались разделяемые проверки и маппинг доменных исключений в HTTP-ответы.
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User, Worker
from app.services import users as user_service
from app.services.orders import (
    InvalidOrderState,
    NotOrderOwner,
    OrderAlreadyCreated,
    OrderNotFound,
    SparePartNotFound,
    StatusNotFound,
    TechnicNotFound,
)


async def require_worker(session: AsyncSession, current_user: User) -> Worker:
    """Возвращает профиль мастера или 403, если его нет."""
    worker = await user_service.get_worker_by_user_id(session, current_user.id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user has no worker profile",
        )
    return worker


def status_seed_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Statuses not seeded. Run seed.",
    )


async def run_order_action(coro):
    """Маппинг доменных исключений заказов в HTTP-ответы."""
    try:
        return await coro
    except OrderNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order or request not found",
        )
    except NotOrderOwner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resource belongs to another user or worker",
        )
    except InvalidOrderState:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid status transition or state",
        )
    except SparePartNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Spare part not found",
        )
    except TechnicNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technic not found",
        )
    except OrderAlreadyCreated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The order has already been created. Adding technic to the "
                "current request is not possible. Create a new request with "
                "the required technic."
            ),
        )
    except StatusNotFound:
        raise status_seed_error()