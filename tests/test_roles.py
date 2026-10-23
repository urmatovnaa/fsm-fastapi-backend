"""Интеграционные тесты ролевого API и новых сценариев.

Проверяются:

* правило перехода заявки в ``COMPLETED`` при создании заказа и назначении
  работника (заявка завершается сразу, заказ -> ``ACCEPTED``);
* жизненный цикл заказа (``EN_ROUTE``/``IN_PROGRESS``/``COMPLETED``/
  ``NOT_COMPLETED``/``CANCELLED``) и неизменность статуса заявки;
* отчёт, запчасти, фотографии результата и изоляция по мастеру;
* доступ пользователя к своим заявкам, результату и отзыву;
* группировка Swagger по ролям.

Работает поверх реального приложения и PostgreSQL (без моков). Требует
запущенный PostgreSQL, применённые миграции и seed.

Запуск:
    pytest tests/test_roles.py
    python -m tests.test_roles
"""
import asyncio
import uuid

import httpx

from app.core.constants import OrderStatuses, RequestStatuses
from app.core.tags import OPENAPI_TAGS, TAG_ADMIN, TAG_USER, TAG_WORKER
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
    from app.core.database import AsyncSessionLocal
    from app.models.users import Worker
    from app.services import users as user_service

    async with AsyncSessionLocal() as session:
        wk_user = await user_service.get_user_by_email(session, email)
        if await user_service.get_worker_by_user_id(session, wk_user.id) is None:
            session.add(Worker(user_id=wk_user.id))
            await session.commit()


async def _create_request(client, headers, description="Leak") -> int:
    r = await client.post(
        "/api/v1/orders/requests",
        headers=headers,
        json={"problem_description": description, "house_number": 1, "urgency": 1},
    )
    assert r.status_code == 201, ("create request", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.SEARCHING_MASTER
    return r.json()["id"]


async def _accept(client, headers, request_id: int) -> int:
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=headers
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    assert r.json()["status"]["name"] == OrderStatuses.ACCEPTED
    return r.json()["id"]


async def _request_status(client, headers, request_id: int) -> str:
    r = await client.get(f"/api/v1/orders/requests/{request_id}", headers=headers)
    assert r.status_code == 200, ("get request", r.status_code, r.text)
    return r.json()["status"]["name"]


# ---------------------------------------------------------------------------
# 8.1 Создание и назначение
# ---------------------------------------------------------------------------
async def _scenario_create_and_assign(client, user_h, worker_h) -> None:
    request_id = await _create_request(client, user_h)

    # До назначения — SEARCHING_MASTER.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.SEARCHING_MASTER
    )

    order_id = await _accept(client, worker_h, request_id)

    # Заявка сразу COMPLETED, заказ ACCEPTED.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )

    # Повторное назначение -> 409.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 409, ("double accept", r.status_code, r.text)

    return request_id, order_id


# ---------------------------------------------------------------------------
# 8.2 Жизненный цикл заказа
# ---------------------------------------------------------------------------
async def _scenario_order_lifecycle(client, user_h, worker_h) -> None:
    request_id, order_id = await _scenario_create_and_assign(
        client, user_h, worker_h
    )

    # ACCEPTED -> EN_ROUTE
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == (
        OrderStatuses.EN_ROUTE
    )
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )

    # EN_ROUTE -> IN_PROGRESS (work_start_time)
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == (
        OrderStatuses.IN_PROGRESS
    )
    assert r.json()["work_start_time"] is not None
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )

    # Повторный start -> 409 (переход IN_PROGRESS -> IN_PROGRESS недопустим).
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_h
    )
    assert r.status_code == 409, ("double start", r.status_code, r.text)

    # IN_PROGRESS -> COMPLETED (work_end_time)
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == (
        OrderStatuses.COMPLETED
    )
    assert r.json()["work_end_time"] is not None
    # Заявка остаётся COMPLETED.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )

    # Терминальный заказ: дальнейшие переходы -> 409.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )
    assert r.status_code == 409, ("terminal complete", r.status_code, r.text)


async def _scenario_not_completed(client, user_h, worker_h) -> int:
    request_id = await _create_request(client, user_h)
    order_id = await _accept(client, worker_h, request_id)

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/not-completed", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == (
        OrderStatuses.NOT_COMPLETED
    )
    # Заявка не откатывается.
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )
    return request_id


async def _scenario_cancelled(client, user_h, worker_h) -> int:
    request_id = await _create_request(client, user_h)
    order_id = await _accept(client, worker_h, request_id)

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/cancel", headers=worker_h
    )
    assert r.status_code == 200 and r.json()["status"]["name"] == (
        OrderStatuses.CANCELLED
    )
    assert await _request_status(client, user_h, request_id) == (
        RequestStatuses.COMPLETED
    )
    return request_id


# ---------------------------------------------------------------------------
# 8.3 Отчёт, запчасти и фотографии
# ---------------------------------------------------------------------------
async def _scenario_report_parts_photos(
    client, user_h, worker_h, foreign_worker_h, spare_part_id: int
) -> None:
    request_id = await _create_request(client, user_h)
    order_id = await _accept(client, worker_h, request_id)

    # Отчёт: чек-лист, описание, стоимость.
    r = await client.put(
        f"/api/v1/orders/work-orders/{order_id}/report",
        headers=worker_h,
        json={
            "checklist": "checked pipes",
            "work_description": "replaced gasket",
            "total_amount": "150.50",
        },
    )
    assert r.status_code == 200, ("report", r.status_code, r.text)
    assert r.json()["checklist"] == "checked pipes"
    assert r.json()["work_description"] == "replaced gasket"
    assert r.json()["total_amount"] == "150.50"

    # Запчасть.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/parts",
        headers=worker_h,
        json={"spare_part_id": spare_part_id, "quantity": 2},
    )
    assert r.status_code == 200, ("add part", r.status_code, r.text)
    parts = r.json()["parts"]
    assert len(parts) == 1
    assert parts[0]["spare_part_id"] == spare_part_id
    assert parts[0]["quantity"] == 2
    assert parts[0]["spare_part_name"] == "Gasket"

    # Фотография результата.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/photos",
        headers=worker_h,
        json={"photo_url": "https://example.com/after.jpg", "photo_type": True},
    )
    assert r.status_code == 200, ("add photo", r.status_code, r.text)
    photos = r.json()["photos"]
    assert len(photos) == 1
    assert photos[0]["photo_url"] == "https://example.com/after.jpg"

    # Чужой мастер не может менять отчёт/добавлять данные -> 403.
    r = await client.put(
        f"/api/v1/orders/work-orders/{order_id}/report",
        headers=foreign_worker_h,
        json={"checklist": "hacked"},
    )
    assert r.status_code == 403, ("foreign report", r.status_code, r.text)

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/parts",
        headers=foreign_worker_h,
        json={"spare_part_id": spare_part_id, "quantity": 1},
    )
    assert r.status_code == 403, ("foreign part", r.status_code, r.text)

    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/photos",
        headers=foreign_worker_h,
        json={"photo_url": "https://example.com/x.jpg"},
    )
    assert r.status_code == 403, ("foreign photo", r.status_code, r.text)

    # Несуществующая запчасть -> 404.
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/parts",
        headers=worker_h,
        json={"spare_part_id": 99999999, "quantity": 1},
    )
    assert r.status_code == 404, ("bad spare part", r.status_code, r.text)

    # Заказ без запчастей валиден: создаём ещё один заказ и добавляем только фото.
    request_id2 = await _create_request(client, user_h)
    order_id2 = await _accept(client, worker_h, request_id2)
    r = await client.get(
        f"/api/v1/orders/work-orders", headers=worker_h
    )
    assert r.status_code == 200
    order2 = next(o for o in r.json() if o["id"] == order_id2)
    assert order2["parts"] == []

    return request_id, order_id


# ---------------------------------------------------------------------------
# 8.4 Доступ пользователя
# ---------------------------------------------------------------------------
async def _scenario_user_access(
    client, user_h, other_user_h, worker_h, request_id: int, order_id: int
) -> None:
    # Пользователь видит только свои заявки.
    r = await client.get("/api/v1/orders/requests", headers=user_h)
    assert r.status_code == 200
    ids = {req["id"] for req in r.json()}
    assert request_id in ids

    r = await client.get("/api/v1/orders/requests", headers=other_user_h)
    assert r.status_code == 200
    other_ids = {req["id"] for req in r.json()}
    assert request_id not in other_ids

    # Чужая заявка не раскрывается -> 404.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}", headers=other_user_h
    )
    assert r.status_code == 404, ("foreign request", r.status_code, r.text)

    # Пользователь видит статус связанного заказа.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}", headers=user_h
    )
    assert r.status_code == 200
    assert len(r.json()["orders"]) >= 1
    assert r.json()["orders"][0]["status"]["name"] in OrderStatuses.ALL

    # Результат работы по своей заявке.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}/result", headers=user_h
    )
    assert r.status_code == 200, ("own result", r.status_code, r.text)
    assert r.json()["work_description"] == "replaced gasket"

    # Результат чужого заказа недоступен -> 404.
    r = await client.get(
        f"/api/v1/orders/requests/{request_id}/result", headers=other_user_h
    )
    assert r.status_code == 404, ("foreign result", r.status_code, r.text)


async def _scenario_review(client, user_h, other_user_h, worker_h) -> None:
    # Завершённый заказ.
    request_id = await _create_request(client, user_h)
    order_id = await _accept(client, worker_h, request_id)
    await client.post(
        f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_h
    )
    await client.post(
        f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_h
    )
    await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )

    # Отзыв по завершённому заказу — ок.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/review",
        headers=user_h,
        json={"client_review": "Great work"},
    )
    assert r.status_code == 200, ("review", r.status_code, r.text)
    assert r.json()["client_review"] == "Great work"

    # Повторный отзыв -> 409.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/review",
        headers=user_h,
        json={"client_review": "Again"},
    )
    assert r.status_code == 409, ("double review", r.status_code, r.text)

    # Отзыв по чужому заказу -> 404.
    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/review",
        headers=other_user_h,
        json={"client_review": "Not mine"},
    )
    assert r.status_code == 404, ("foreign review", r.status_code, r.text)

    # Отзыв по NOT_COMPLETED -> 409.
    rid_nc = await _create_request(client, user_h)
    oid_nc = await _accept(client, worker_h, rid_nc)
    await client.post(
        f"/api/v1/orders/work-orders/{oid_nc}/not-completed", headers=worker_h
    )
    r = await client.post(
        f"/api/v1/orders/requests/{rid_nc}/review",
        headers=user_h,
        json={"client_review": "no"},
    )
    assert r.status_code == 409, ("review not completed", r.status_code, r.text)

    # Отзыв по CANCELLED -> 409.
    rid_c = await _create_request(client, user_h)
    oid_c = await _accept(client, worker_h, rid_c)
    await client.post(
        f"/api/v1/orders/work-orders/{oid_c}/cancel", headers=worker_h
    )
    r = await client.post(
        f"/api/v1/orders/requests/{rid_c}/review",
        headers=user_h,
        json={"client_review": "no"},
    )
    assert r.status_code == 409, ("review cancelled", r.status_code, r.text)


async def _scenario_history(client, user_h, worker_h) -> None:
    # История содержит завершённые/невыполненные/отменённые заказы мастера.
    rid = await _create_request(client, user_h)
    oid = await _accept(client, worker_h, rid)
    await client.post(
        f"/api/v1/orders/work-orders/{oid}/en-route", headers=worker_h
    )
    await client.post(
        f"/api/v1/orders/work-orders/{oid}/start", headers=worker_h
    )
    await client.post(
        f"/api/v1/orders/work-orders/{oid}/complete", headers=worker_h
    )

    r = await client.get("/api/v1/orders/work-orders/history", headers=worker_h)
    assert r.status_code == 200, ("history", r.status_code, r.text)
    hist_ids = {o["id"] for o in r.json()}
    assert oid in hist_ids
    assert all(
        o["status"]["name"]
        in (
            OrderStatuses.COMPLETED,
            OrderStatuses.NOT_COMPLETED,
            OrderStatuses.CANCELLED,
        )
        for o in r.json()
    )

    # Фильтр по статусу COMPLETED.
    r = await client.get(
        "/api/v1/orders/work-orders/history",
        headers=worker_h,
        params={"status": OrderStatuses.COMPLETED},
    )
    assert r.status_code == 200
    assert all(o["status"]["name"] == OrderStatuses.COMPLETED for o in r.json())

    # Неприменимый статус фильтра -> 409.
    r = await client.get(
        "/api/v1/orders/work-orders/history",
        headers=worker_h,
        params={"status": OrderStatuses.ACCEPTED},
    )
    assert r.status_code == 409, ("bad history filter", r.status_code, r.text)


# ---------------------------------------------------------------------------
# 8.5 Swagger
# ---------------------------------------------------------------------------
async def _scenario_swagger(client) -> None:
    schema = app.openapi()
    tag_names = {t["name"] for t in schema["tags"]}
    for tag in OPENAPI_TAGS:
        assert tag["name"] in tag_names
    assert {TAG_USER, TAG_WORKER, TAG_ADMIN} <= tag_names

    paths = schema["paths"]

    # Пользовательские endpoints.
    assert paths["/api/v1/orders/requests"]["post"]["tags"] == [TAG_USER]
    assert paths["/api/v1/orders/requests"]["get"]["tags"] == [TAG_USER]
    assert paths["/api/v1/orders/requests/{request_id}"]["get"]["tags"] == [TAG_USER]

    # Мастерские endpoints.
    assert paths["/api/v1/orders/work-orders"]["get"]["tags"] == [TAG_WORKER]
    assert paths["/api/v1/orders/work-orders/{work_order_id}/report"]["put"][
        "tags"
    ] == [TAG_WORKER]
    assert paths["/api/v1/orders/requests/{request_id}/accept"]["post"][
        "tags"
    ] == [TAG_WORKER]

    # Административные endpoints.
    assert paths["/api/v1/control/users"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/technics"]["post"]["tags"] == [TAG_ADMIN]


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
async def run_roles_flow() -> None:
    await _seed()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        suffix = uuid.uuid4().hex[:8]
        user_email = f"roles_user_{suffix}@example.com"
        other_email = f"roles_other_{suffix}@example.com"
        worker_email = f"roles_worker_{suffix}@example.com"
        foreign_worker_email = f"roles_fworker_{suffix}@example.com"
        admin_email = f"roles_admin_{suffix}@example.com"

        await _register(client, user_email)
        await _register(client, other_email)
        await _register(client, worker_email)
        await _register(client, foreign_worker_email)
        await _register(client, admin_email, is_admin=True)

        await _make_worker(worker_email)
        await _make_worker(foreign_worker_email)

        user_h = await _login(client, user_email)
        other_h = await _login(client, other_email)
        worker_h = await _login(client, worker_email)
        foreign_worker_h = await _login(client, foreign_worker_email)
        admin_h = await _login(client, admin_email)

        # Админ создаёт запчасть для сценария с запчастями.
        r = await client.post(
            "/api/v1/control/spare-parts",
            headers=admin_h,
            json={"name": "Gasket", "description": "rubber", "price": "9.99"},
        )
        assert r.status_code == 201, ("spare part", r.status_code, r.text)
        spare_part_id = r.json()["id"]

        await _scenario_order_lifecycle(client, user_h, worker_h)
        await _scenario_not_completed(client, user_h, worker_h)
        await _scenario_cancelled(client, user_h, worker_h)

        request_id, order_id = await _scenario_report_parts_photos(
            client, user_h, worker_h, foreign_worker_h, spare_part_id
        )
        await _scenario_user_access(
            client, user_h, other_h, worker_h, request_id, order_id
        )
        await _scenario_review(client, user_h, other_h, worker_h)
        await _scenario_history(client, user_h, worker_h)
        await _scenario_swagger(client)

    print("ROLES FLOW: OK")


def test_roles_flow() -> None:
    asyncio.run(run_roles_flow())


if __name__ == "__main__":
    asyncio.run(run_roles_flow())