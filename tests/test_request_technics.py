"""Тесты добавления техники к заявке пользователем (ТЗ No3).

Проверяется:

* указание одной/нескольких единиц техники при создании ``Request``;
* сохранение техники через существующую связь ``RequestTechnic``
  (новые таблицы/поля не создаются);
* сценарий А — добавление/изменение техники у заявки без созданного заказа
  (статус ``SEARCHING_MASTER``): состав техники меняется, новый ``Order``
  не создаётся;
* сценарий Б — заказ уже создан (работник назначен): изменение запрещено,
  ``Request`` не меняется, новый ``Order`` не создаётся, ответ ``409 Conflict``
  с сообщением о необходимости создать новую заявку;
* проверки владения (чужая заявка -> 404) и существования техники (-> 404).

Работает поверх реального приложения и PostgreSQL (без моков). Требует
запущенный PostgreSQL, применённые миграции и seed.

Запуск:
    pytest tests/test_request_technics.py
    python -m tests.test_request_technics
"""
import asyncio
import uuid

import httpx

from app.core.constants import OrderStatuses, RequestStatuses
from app.main import app

password = "secret123"


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
async def _seed() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.seed import seed_all

    async with AsyncSessionLocal() as session:
        await seed_all(session)


async def _register(client, email: str, *, is_admin: bool = False) -> int:
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
    return r.json()["id"]


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


async def _create_technic(client, admin_h, name: str) -> int:
    r = await client.post(
        "/api/v1/control/technics", headers=admin_h, json={"name": name}
    )
    assert r.status_code == 201, ("create technic", r.status_code, r.text)
    return r.json()["id"]


def _technic_ids(body: dict) -> list[int]:
    return [t["id"] for t in body.get("technics", [])]


# ---------------------------------------------------------------------------
# Сценарий 1: техника при создании заявки
# ---------------------------------------------------------------------------
async def _scenario_create_with_technics(client, user_h, admin_h) -> tuple[int, int]:
    t1 = await _create_technic(client, admin_h, "Drill")
    t2 = await _create_technic(client, admin_h, "Ladder")

    # Заявка сразу с несколькими единицами техники.
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={
            "problem_description": "Mount shelf",
            "house_number": 1,
            "urgency": 1,
            "technic_ids": [t1, t2],
        },
    )
    assert r.status_code == 201, ("create with technics", r.status_code, r.text)
    body = r.json()
    assert body["status"]["name"] == RequestStatuses.SEARCHING_MASTER
    assert sorted(_technic_ids(body)) == sorted([t1, t2]), body

    # Заявка без техники — пустой состав.
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={"problem_description": "No technic", "house_number": 2},
    )
    assert r.status_code == 201
    assert _technic_ids(r.json()) == []

    # Несуществующая техника при создании -> 404.
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={"problem_description": "Bad", "technic_ids": [99999999]},
    )
    assert r.status_code == 404, ("bad technic create", r.status_code, r.text)

    # Дубликаты ID не создают дубликатов связей.
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={"problem_description": "Dup", "technic_ids": [t1, t1]},
    )
    assert r.status_code == 201
    assert _technic_ids(r.json()) == [t1], ("technic dedup", r.text)

    return t1, t2


# ---------------------------------------------------------------------------
# Сценарий А: добавление техники в существующую заявку (заказа нет)
# ---------------------------------------------------------------------------
async def _scenario_add_before_order(client, user_h, admin_h, t1: int, t2: int) -> None:
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={"problem_description": "Scenario A", "technic_ids": [t1]},
    )
    assert r.status_code == 201, ("create", r.status_code, r.text)
    request_id = r.json()["id"]
    assert _technic_ids(r.json()) == [t1]

    # Изменяем состав техники (замена на t2).
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=user_h,
        json={"technic_ids": [t2]},
    )
    assert r.status_code == 200, ("scenario A add", r.status_code, r.text)
    assert _technic_ids(r.json()) == [t2], r.text

    # Добавляем несколько единиц техники.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=user_h,
        json={"technic_ids": [t1, t2]},
    )
    assert r.status_code == 200, ("scenario A multi", r.status_code, r.text)
    assert sorted(_technic_ids(r.json())) == sorted([t1, t2])

    # Новый Order не создавался: статус заявки не менялся.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}", headers=user_h
    )
    assert r.status_code == 200
    assert r.json()["status"]["name"] == RequestStatuses.SEARCHING_MASTER
    assert r.json()["orders"] == [], ("no order must be created", r.text)

    # Чужая заявка -> 404.
    other_email = f"tech_other_{uuid.uuid4().hex[:8]}@example.com"
    await _register(client, other_email)
    other_h = await _login(client, other_email)
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=other_h,
        json={"technic_ids": [t1]},
    )
    assert r.status_code == 404, ("foreign request", r.status_code, r.text)

    # Несуществующая заявка -> 404.
    r = await client.post(
        "/api/v1/orders/requests/99999999/technics",
        headers=user_h,
        json={"technic_ids": [t1]},
    )
    assert r.status_code == 404, ("missing request", r.status_code, r.text)

    # Несуществующая техника -> 404.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=user_h,
        json={"technic_ids": [99999999]},
    )
    assert r.status_code == 404, ("missing technic", r.status_code, r.text)

    # Пустой список техники -> 422 (валидация схемы).
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=user_h,
        json={"technic_ids": []},
    )
    assert r.status_code == 422, ("empty technic list", r.status_code, r.text)


# ---------------------------------------------------------------------------
# Сценарий Б: заказ уже создан (работник назначен) -> запрет
# ---------------------------------------------------------------------------
async def _scenario_after_order(client, user_h, worker_h, t1: int, t2: int) -> None:
    r = await client.post(
        "/api/v1/orders/requests",
        headers=user_h,
        json={"problem_description": "Scenario B", "technic_ids": [t1]},
    )
    assert r.status_code == 201, ("create", r.status_code, r.text)
    request_id = r.json()["id"]

    # Работник принимает заявку -> создаётся заказ, работник назначен.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    order_id = r.json()["id"]
    assert r.json()["status"]["name"] == OrderStatuses.ACCEPTED

    # Попытка добавить технику -> 409 с сообщением.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/technics",
        headers=user_h,
        json={"technic_ids": [t2]},
    )
    assert r.status_code == 409, ("scenario B blocked", r.status_code, r.text)
    detail = r.json()["detail"].lower()
    assert "заказ уже создан" in detail, r.text
    assert "создайте новую заявку" in detail, r.text

    # Заявка не изменилась — состав техники прежний.
    r = await client.get(f"/api/v1/orders/requests/{request_id}", headers=user_h)
    assert r.status_code == 200
    assert _technic_ids(r.json()) == [t1], ("request must be unchanged", r.text)

    # Новый Order не создан — ровно один заказ по заявке.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}/orders", headers=user_h
    )
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) == 1 and orders[0]["id"] == order_id, ("no new order", r.text)


async def run_technic_flow() -> None:
    await _seed()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        suffix = uuid.uuid4().hex[:8]
        user_email = f"tech_user_{suffix}@example.com"
        worker_email = f"tech_worker_{suffix}@example.com"
        admin_email = f"tech_admin_{suffix}@example.com"

        await _register(client, user_email)
        await _register(client, worker_email)
        await _register(client, admin_email, is_admin=True)
        await _make_worker(worker_email)

        user_h = await _login(client, user_email)
        worker_h = await _login(client, worker_email)
        admin_h = await _login(client, admin_email)

        t1, t2 = await _scenario_create_with_technics(client, user_h, admin_h)
        await _scenario_add_before_order(client, user_h, admin_h, t1, t2)
        await _scenario_after_order(client, user_h, worker_h, t1, t2)

    print("REQUEST TECHNICS FLOW: OK")


def test_request_technic_flow() -> None:
    asyncio.run(run_technic_flow())


if __name__ == "__main__":
    asyncio.run(run_technic_flow())