"""Тесты статусов заявок и заказов (ТЗ No2).

Две группы:

* Unit-тесты карт допустимых переходов (БД не требуется) — проверяют
  централизованную валидацию переходов.
* Integration-тесты поверх реального приложения и PostgreSQL — проверяют
  фактический жизненный цикл Request/Order через API и хранение статусов
  в единой таблице `statuses`.

Integration-тесты не меняют схему БД: только наполняют существующую
таблицу `statuses` (idempotent seed) и пишут обычные строки заявок/заказов.

Запуск:
    pytest tests/test_statuses.py
    python -m tests.test_statuses
"""
import asyncio
import uuid

import httpx

from app.core.constants import (
    ORDER_TRANSITIONS,
    REQUEST_TRANSITIONS,
    OrderStatuses,
    RequestStatuses,
    is_valid_transition,
)
from app.main import app

# ---------------------------------------------------------------------------
# Unit-тесты: карты переходов
# ---------------------------------------------------------------------------


def test_request_valid_transitions():
    searching = RequestStatuses.SEARCHING_MASTER
    assert is_valid_transition(searching, RequestStatuses.REJECTED, REQUEST_TRANSITIONS)
    assert is_valid_transition(searching, RequestStatuses.COMPLETED, REQUEST_TRANSITIONS)
    assert is_valid_transition(searching, RequestStatuses.CANCELLED, REQUEST_TRANSITIONS)


def test_request_invalid_transitions():
    # Из терминальных состояний переходов нет.
    for terminal in (
        RequestStatuses.REJECTED,
        RequestStatuses.COMPLETED,
        RequestStatuses.CANCELLED,
    ):
        assert not is_valid_transition(
            terminal, RequestStatuses.SEARCHING_MASTER, REQUEST_TRANSITIONS
        )
    # Нет перехода SEARCHING_MASTER -> SEARCHING_MASTER.
    assert not is_valid_transition(
        RequestStatuses.SEARCHING_MASTER,
        RequestStatuses.SEARCHING_MASTER,
        REQUEST_TRANSITIONS,
    )
    # Нет перехода из REJECTED в COMPLETED и т.п.
    assert not is_valid_transition(
        RequestStatuses.REJECTED, RequestStatuses.COMPLETED, REQUEST_TRANSITIONS
    )
    # None (нет статуса) не валиден.
    assert not is_valid_transition(
        None, RequestStatuses.CANCELLED, REQUEST_TRANSITIONS
    )


def test_order_happy_path_transitions():
    assert is_valid_transition(
        OrderStatuses.ACCEPTED, OrderStatuses.EN_ROUTE, ORDER_TRANSITIONS
    )
    assert is_valid_transition(
        OrderStatuses.EN_ROUTE, OrderStatuses.IN_PROGRESS, ORDER_TRANSITIONS
    )
    assert is_valid_transition(
        OrderStatuses.IN_PROGRESS, OrderStatuses.COMPLETED, ORDER_TRANSITIONS
    )


def test_order_not_completed_transitions():
    for current in (
        OrderStatuses.ACCEPTED,
        OrderStatuses.EN_ROUTE,
        OrderStatuses.IN_PROGRESS,
    ):
        assert is_valid_transition(
            current, OrderStatuses.NOT_COMPLETED, ORDER_TRANSITIONS
        )


def test_order_cancelled_transitions():
    for current in (OrderStatuses.ACCEPTED, OrderStatuses.EN_ROUTE):
        assert is_valid_transition(current, OrderStatuses.CANCELLED, ORDER_TRANSITIONS)
    # ИЗ IN_PROGRESS отменить нельзя.
    assert not is_valid_transition(
        OrderStatuses.IN_PROGRESS, OrderStatuses.CANCELLED, ORDER_TRANSITIONS
    )


def test_order_invalid_transitions():
    # Нельзя перескочить шаги основного сценария.
    assert not is_valid_transition(
        OrderStatuses.ACCEPTED, OrderStatuses.IN_PROGRESS, ORDER_TRANSITIONS
    )
    assert not is_valid_transition(
        OrderStatuses.ACCEPTED, OrderStatuses.COMPLETED, ORDER_TRANSITIONS
    )
    # Терминальные состояния закрыты.
    for terminal in (
        OrderStatuses.COMPLETED,
        OrderStatuses.NOT_COMPLETED,
        OrderStatuses.CANCELLED,
    ):
        assert not is_valid_transition(
            terminal, OrderStatuses.EN_ROUTE, ORDER_TRANSITIONS
        )
    assert not is_valid_transition(None, OrderStatuses.ACCEPTED, ORDER_TRANSITIONS)


# ---------------------------------------------------------------------------
# Integration-тесты: реальный жизненный цикл
# ---------------------------------------------------------------------------

password = "secret123"


async def _register(client, email: str, *, is_admin: bool = False) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test User",
            "email": email,
            "password": password,
            "password_confirmation": password,
            "is_admin": is_admin,
        },
    )
    assert r.status_code == 201, ("register", email, r.status_code, r.text)


async def _login(client, email: str) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, ("login", email, r.status_code, r.text)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _make_worker(email: str) -> None:
    """Создаёт профиль Worker для зарегистрированного пользователя (idempotent)."""
    from app.core.database import AsyncSessionLocal
    from app.models.users import Worker
    from app.services import users as user_service

    async with AsyncSessionLocal() as session:
        wk_user = await user_service.get_user_by_email(session, email)
        if await user_service.get_worker_by_user_id(session, wk_user.id) is None:
            session.add(Worker(user_id=wk_user.id))
            await session.commit()


async def _seed() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.seed import seed_all

    async with AsyncSessionLocal() as session:
        await seed_all(session)


async def _create_request(client, headers: dict[str, str]) -> int:
    r = await client.post(
        "/api/v1/orders/requests",
        headers=headers,
        json={"problem_description": "Leak", "house_number": 1, "urgency": 1},
    )
    assert r.status_code == 201, ("create request", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.SEARCHING_MASTER
    return r.json()["id"]


async def _request_status(client, headers, request_id: int) -> str:
    r = await client.get(f"/api/v1/orders/requests/{request_id}", headers=headers)
    assert r.status_code == 200, ("get request", r.status_code, r.text)
    return r.json()["status"]["name"]


async def _scenario_happy_path(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.ACCEPTED
    order_id = r.json()["id"]

    # Заявка ещё в поиске мастера, пока заказ активен.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.SEARCHING_MASTER
    )

    # Повторный accept -> 409 (активный заказ уже есть).
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 409, ("double accept", r.status_code, r.text)

    # Нельзя завершить из ACCEPTED.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )
    assert r.status_code == 409, ("complete from accepted", r.status_code, r.text)

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == OrderStatuses.EN_ROUTE

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_h
    )
    assert (
        r.status_code == 200
        and r.json()["status"]["name"] == OrderStatuses.IN_PROGRESS
    )

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )
    assert r.status_code == 200, ("complete", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.COMPLETED
    assert r.json()["work_end_time"] is not None

    # Заявка завершена вместе с заказом.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )

    # Терминальный заказ: дальнейшие переходы -> 409.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_h
    )
    assert r.status_code == 409, ("terminal transition", r.status_code, r.text)


async def _scenario_not_completed_and_reuse(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    first_order_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/orders/work-orders/{first_order_id}/en-route", headers=worker_h
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/orders/work-orders/{first_order_id}/not-completed", headers=worker_h
    )
    assert r.status_code == 200, ("not completed", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.NOT_COMPLETED

    # Заявка остаётся в поиске мастера — можно создать новый заказ.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.SEARCHING_MASTER
    )

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("re-accept after not completed", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.ACCEPTED
    assert r.json()["id"] != first_order_id


async def _scenario_order_cancel(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    order_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/cancel", headers=worker_h
    )
    assert r.status_code == 200, ("cancel order", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.CANCELLED

    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.SEARCHING_MASTER
    )


async def _scenario_request_reject(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/reject", headers=user_h
    )
    assert r.status_code == 200, ("reject", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.REJECTED

    # Повторный reject из терминального состояния -> 409.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/reject", headers=user_h
    )
    assert r.status_code == 409, ("double reject", r.status_code, r.text)

    # Нельзя принять отклонённую заявку.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 409, ("accept rejected", r.status_code, r.text)


async def _scenario_request_cancel(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/cancel", headers=user_h
    )
    assert r.status_code == 200, ("cancel request", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.CANCELLED

    # Отменённую заявку нельзя принять.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 409, ("accept cancelled", r.status_code, r.text)


async def _scenario_seed_idempotent() -> None:
    """Повторный seed не создаёт дубликатов статусов."""
    from app.core.constants import ALL_STATUS_NAMES
    from app.core.database import AsyncSessionLocal
    from app.models.orders import Status
    from app.services.seed import seed_all
    from sqlalchemy import func, select

    async with AsyncSessionLocal() as session:
        await seed_all(session)
        await seed_all(session)
        rows = await session.execute(
            select(Status.name, func.count()).group_by(Status.name)
        )
        counts = dict(rows.all())

    for name in ALL_STATUS_NAMES:
        assert counts.get(name) == 1, ("duplicate status", name, counts.get(name))


async def run_status_flow() -> None:
    await _seed()
    await _scenario_seed_idempotent()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        suffix = uuid.uuid4().hex[:8]
        user_email = f"status_user_{suffix}@example.com"
        worker_email = f"status_worker_{suffix}@example.com"

        await _register(client, user_email)
        await _register(client, worker_email)
        await _make_worker(worker_email)

        admin_email = f"status_admin_{suffix}@example.com"
        await _register(client, admin_email, is_admin=True)

        user_h = await _login(client, user_email)
        worker_h = await _login(client, worker_email)
        admin_h = await _login(client, admin_email)

        await _scenario_happy_path(client, user_h, worker_h)
        await _scenario_not_completed_and_reuse(client, user_h, worker_h)
        await _scenario_order_cancel(client, user_h, worker_h)
        await _scenario_request_reject(client, user_h, worker_h)
        await _scenario_request_cancel(client, user_h, worker_h)
        await _scenario_admin_list_users(client, admin_h, user_h, user_email, worker_email)

    print("STATUS FLOW: OK")


async def _scenario_admin_list_users(
    client, admin_h, user_h, user_email: str, worker_email: str
) -> None:
    """GET /control/users: только админ; отдаёт роли user/worker/admin."""
    # Не-админ -> 403.
    r = await client.get("/api/v1/control/users", headers=user_h)
    assert r.status_code == 403, ("non-admin users", r.status_code, r.text)

    # Админ -> 200 со списком.
    r = await client.get("/api/v1/control/users", headers=admin_h)
    assert r.status_code == 200, ("admin users", r.status_code, r.text)
    users = r.json()
    by_email = {u["email"]: u for u in users}

    assert by_email[user_email]["role"] == "user"
    assert by_email[worker_email]["role"] == "worker"
    assert by_email[worker_email]["worker_id"] is not None
    # Пароли не утекают в ответ.
    assert all("password" not in u for u in users)


def test_status_flow() -> None:
    """pytest-обёртка интеграционного сценария."""
    asyncio.run(run_status_flow())


if __name__ == "__main__":
    asyncio.run(run_status_flow())