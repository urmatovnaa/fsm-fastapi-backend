"""Интеграционные тесты административного API (tag ``Admin``).

Проверяются:

* серверная авторизация (401/403/404/409);
* просмотр и редактирование пользователей и работников;
* создание работника с новым пользователем и откат при конфликте email;
* управление навыками и расписанием работника;
* фильтрация заявок по статусу, пользователю и работнику (и комбинации);
* полная информация о заявке/заказе, назначенные работники и отчёт;
* CRUD справочников (техника, запчасти, склады) и складских остатков;
* просмотр отзывов (заказы без отзыва исключены);
* сохранение ролевой группировки Swagger.

Работает поверх реального приложения и PostgreSQL (без моков). Требует
запущенный PostgreSQL, применённые миграции и seed.

Запуск:
    pytest tests/test_admin.py
    python -m tests.test_admin
"""
import asyncio
import uuid

import httpx

from app.core.constants import OrderStatuses, RequestStatuses
from app.core.tags import TAG_ADMIN, TAG_USER, TAG_WORKER
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


async def _make_worker(email: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.users import Worker
    from app.services import users as user_service

    async with AsyncSessionLocal() as session:
        wk_user = await user_service.get_user_by_email(session, email)
        worker = await user_service.get_worker_by_user_id(session, wk_user.id)
        if worker is None:
            worker = Worker(user_id=wk_user.id)
            session.add(worker)
            await session.commit()
            await session.refresh(worker)
    return worker.id


async def _worker_id_by_email(client, admin_h, email: str) -> int:
    r = await client.get("/api/v1/control/workers", headers=admin_h)
    assert r.status_code == 200, ("list workers", r.status_code, r.text)
    for w in r.json():
        if w["email"] == email:
            return w["id"]
    raise AssertionError(f"worker for {email} not found")


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------
async def _scenario_auth(client, admin_h, user_h, worker_h) -> None:
    # Нет токена -> 401.
    r = await client.get("/api/v1/control/users")
    assert r.status_code == 401, ("no token", r.status_code, r.text)

    # Недействительный токен -> 401.
    r = await client.get(
        "/api/v1/control/users", headers={"Authorization": "Bearer invalid"}
    )
    assert r.status_code == 401, ("bad token", r.status_code, r.text)

    # Обычный пользователь -> 403.
    r = await client.get("/api/v1/control/users", headers=user_h)
    assert r.status_code == 403, ("user forbidden", r.status_code, r.text)

    # Мастер без прав администратора -> 403.
    r = await client.get("/api/v1/control/users", headers=worker_h)
    assert r.status_code == 403, ("worker forbidden", r.status_code, r.text)
    r = await client.get("/api/v1/control/requests", headers=worker_h)
    assert r.status_code == 403, ("worker requests forbidden", r.status_code, r.text)

    # Администратор -> 200.
    r = await client.get("/api/v1/control/users", headers=admin_h)
    assert r.status_code == 200, ("admin users", r.status_code, r.text)
    assert all("password" not in u for u in r.json())

    # Отсутствующий пользователь -> 404.
    r = await client.get("/api/v1/control/users/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing user", r.status_code, r.text)


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------
async def _scenario_users(client, admin_h, owner_id: int, other_email: str) -> None:
    # Профиль по ID.
    r = await client.get(f"/api/v1/control/users/{owner_id}", headers=admin_h)
    assert r.status_code == 200 and r.json()["id"] == owner_id

    # Изменение разрешённых данных.
    r = await client.patch(
        f"/api/v1/control/users/{owner_id}",
        headers=admin_h,
        json={"full_name": "Renamed Owner", "phone": "+10000000000"},
    )
    assert r.status_code == 200, ("patch user", r.status_code, r.text)
    assert r.json()["full_name"] == "Renamed Owner"
    assert r.json()["phone"] == "+10000000000"
    # is_admin не повышается массовым обновлением.
    assert r.json()["is_admin"] is False

    # Конфликт email -> 409.
    r = await client.patch(
        f"/api/v1/control/users/{owner_id}",
        headers=admin_h,
        json={"email": other_email},
    )
    assert r.status_code == 409, ("email conflict", r.status_code, r.text)

    # Отсутствующий пользователь -> 404.
    r = await client.patch(
        "/api/v1/control/users/99999999", headers=admin_h, json={"full_name": "X"}
    )
    assert r.status_code == 404, ("patch missing", r.status_code, r.text)


# ---------------------------------------------------------------------------
# Работники, навыки, расписание
# ---------------------------------------------------------------------------
async def _scenario_workers(client, admin_h, technic_id: int) -> int:
    suffix = uuid.uuid4().hex[:8]
    email = f"admin_created_worker_{suffix}@example.com"

    # Создание работника вместе с новым профилем пользователя.
    r = await client.post(
        "/api/v1/control/workers",
        headers=admin_h,
        json={
            "full_name": "New Worker",
            "email": email,
            "password": password,
            "experience": 3,
            "latitude": 10,
            "longitude": 20,
        },
    )
    assert r.status_code == 201, ("create worker", r.status_code, r.text)
    worker = r.json()
    worker_id = worker["id"]
    assert worker["email"] == email
    assert worker["experience"] == 3

    # Повторный email -> 409 (полный откат: пользователь без профиля не создан).
    r = await client.post(
        "/api/v1/control/workers",
        headers=admin_h,
        json={"full_name": "Dup", "email": email, "password": password},
    )
    assert r.status_code == 409, ("dup worker email", r.status_code, r.text)

    # Список работников содержит нового.
    r = await client.get("/api/v1/control/workers", headers=admin_h)
    assert r.status_code == 200
    assert any(w["id"] == worker_id for w in r.json())

    # Профиль работника.
    r = await client.get(f"/api/v1/control/workers/{worker_id}", headers=admin_h)
    assert r.status_code == 200, ("worker detail", r.status_code, r.text)
    detail = r.json()
    assert detail["user"]["email"] == email
    assert "workload" in detail
    assert detail["skills"] == []

    # Изменение профиля.
    r = await client.patch(
        f"/api/v1/control/workers/{worker_id}",
        headers=admin_h,
        json={"experience": 5, "latitude": 11},
    )
    assert r.status_code == 200 and r.json()["experience"] == 5

    # Отсутствующий работник -> 404.
    r = await client.get("/api/v1/control/workers/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing worker", r.status_code, r.text)

    # --- Навыки ---
    r = await client.post(
        f"/api/v1/control/workers/{worker_id}/skills",
        headers=admin_h,
        json={"technic_id": technic_id},
    )
    assert r.status_code == 201, ("add skill", r.status_code, r.text)
    skill_id = r.json()["id"]
    assert r.json()["technic_id"] == technic_id

    # Повторное добавление — без дубликата.
    r = await client.post(
        f"/api/v1/control/workers/{worker_id}/skills",
        headers=admin_h,
        json={"technic_id": technic_id},
    )
    assert r.status_code == 201
    r = await client.get(
        f"/api/v1/control/workers/{worker_id}/skills", headers=admin_h
    )
    assert len(r.json()) == 1, ("skill dedup", r.text)

    # Несуществующая техника -> 404.
    r = await client.post(
        f"/api/v1/control/workers/{worker_id}/skills",
        headers=admin_h,
        json={"technic_id": 99999999},
    )
    assert r.status_code == 404, ("bad technic", r.status_code, r.text)

    # Удаление навыка.
    r = await client.delete(
        f"/api/v1/control/workers/{worker_id}/skills/{skill_id}", headers=admin_h
    )
    assert r.status_code == 204, ("delete skill", r.status_code, r.text)
    r = await client.delete(
        f"/api/v1/control/workers/{worker_id}/skills/{skill_id}", headers=admin_h
    )
    assert r.status_code == 404, ("re-delete skill", r.status_code, r.text)

    # --- Расписание ---
    r = await client.post(
        f"/api/v1/control/workers/{worker_id}/schedules",
        headers=admin_h,
        json={"start_time": "09:00:00", "end_time": "18:00:00"},
    )
    assert r.status_code == 201, ("create schedule", r.status_code, r.text)
    schedule_id = r.json()["id"]

    # Некорректный интервал -> 400.
    r = await client.post(
        f"/api/v1/control/workers/{worker_id}/schedules",
        headers=admin_h,
        json={"start_time": "18:00:00", "end_time": "09:00:00"},
    )
    assert r.status_code == 400, ("bad interval", r.status_code, r.text)

    # Изменение и удаление.
    r = await client.patch(
        f"/api/v1/control/workers/{worker_id}/schedules/{schedule_id}",
        headers=admin_h,
        json={"end_time": "20:00:00"},
    )
    assert r.status_code == 200, ("patch schedule", r.status_code, r.text)

    r = await client.delete(
        f"/api/v1/control/workers/{worker_id}/schedules/{schedule_id}",
        headers=admin_h,
    )
    assert r.status_code == 204, ("delete schedule", r.status_code, r.text)

    return worker_id


# ---------------------------------------------------------------------------
# Заявки, заказы, отзывы
# ---------------------------------------------------------------------------
async def _create_completed_reviewed(
    client, owner_h, worker_h
) -> tuple[int, int]:
    r = await client.post(
        "/api/v1/orders/requests",
        headers=owner_h,
        json={"problem_description": "Admin flow", "house_number": 3, "urgency": 2},
    )
    assert r.status_code == 201, ("create request", r.status_code, r.text)
    request_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    order_id = r.json()["id"]

    await client.put(
        f"/api/v1/orders/work-orders/{order_id}/report",
        headers=worker_h,
        json={"work_description": "done well", "total_amount": "99.00"},
    )
    await client.post(
        f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_h
    )
    await client.post(
        f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_h
    )
    r = await client.post(
        f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_h
    )
    assert r.status_code == 200, ("complete", r.status_code, r.text)

    r = await client.post(
        f"/api/v1/orders/requests/{request_id}/review",
        headers=owner_h,
        json={"client_review": "Excellent service"},
    )
    assert r.status_code == 200, ("review", r.status_code, r.text)
    return request_id, order_id


async def _scenario_requests_orders(
    client,
    admin_h,
    owner_h,
    owner_id: int,
    worker_h,
    worker_id: int,
) -> None:
    request_id, order_id = await _create_completed_reviewed(
        client, owner_h, worker_h
    )

    # Фильтр по статусу (заявка после принятия -> COMPLETED).
    r = await client.get(
        "/api/v1/control/requests",
        headers=admin_h,
        params={"status": RequestStatuses.COMPLETED},
    )
    assert r.status_code == 200, ("filter status", r.status_code, r.text)
    # Все возвращённые заявки имеют запрошенный статус.
    assert all(
        x["status"]["name"] == RequestStatuses.COMPLETED for x in r.json()
    )

    # Фильтр по пользователю (+ статус), чтобы гарантированно найти свою заявку
    # в пределах страницы: проверяем и корректность фильтров, и присутствие.
    r = await client.get(
        "/api/v1/control/requests",
        headers=admin_h,
        params={
            "user_id": owner_id,
            "status": RequestStatuses.COMPLETED,
        },
    )
    assert r.status_code == 200
    assert all(x["user"]["id"] == owner_id for x in r.json())
    assert any(x["id"] == request_id for x in r.json())

    # Фильтр по работнику.
    r = await client.get(
        "/api/v1/control/requests", headers=admin_h, params={"worker_id": worker_id}
    )
    assert r.status_code == 200, ("filter worker", r.status_code, r.text)
    assert any(x["id"] == request_id for x in r.json())

    # Комбинирование фильтров.
    r = await client.get(
        "/api/v1/control/requests",
        headers=admin_h,
        params={
            "status": RequestStatuses.COMPLETED,
            "user_id": owner_id,
            "worker_id": worker_id,
        },
    )
    assert r.status_code == 200
    assert any(x["id"] == request_id for x in r.json())

    # Полная карточка заявки.
    r = await client.get(
        f"/api/v1/control/requests/{request_id}", headers=admin_h
    )
    assert r.status_code == 200, ("request detail", r.status_code, r.text)
    detail = r.json()
    assert detail["user"]["id"] == owner_id
    assert len(detail["orders"]) >= 1
    assert len(detail["orders"][0]["workers"]) >= 1
    assert any(w["id"] == worker_id for w in detail["orders"][0]["workers"])

    # Отсутствующая заявка -> 404.
    r = await client.get("/api/v1/control/requests/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing request", r.status_code, r.text)

    # Заказ: отчёт, стоимость, работники, статус.
    r = await client.get(f"/api/v1/control/orders/{order_id}", headers=admin_h)
    assert r.status_code == 200, ("order detail", r.status_code, r.text)
    order = r.json()
    assert order["status"]["name"] == OrderStatuses.COMPLETED
    assert order["work_description"] == "done well"
    assert any(w["id"] == worker_id for w in order["workers"])

    # Отсутствующий заказ -> 404.
    r = await client.get("/api/v1/control/orders/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing order", r.status_code, r.text)

    # --- Отзывы ---
    r = await client.get("/api/v1/control/reviews", headers=admin_h)
    assert r.status_code == 200, ("reviews", r.status_code, r.text)
    reviews = r.json()
    assert any(x["order_id"] == order_id for x in reviews)
    # Заказы без отзыва не попадают в выборку.
    assert all(x["client_review"] for x in reviews)

    # Фильтр отзывов по пользователю.
    r = await client.get(
        "/api/v1/control/reviews", headers=admin_h, params={"user_id": owner_id}
    )
    assert r.status_code == 200
    assert all(x["user_id"] == owner_id for x in r.json())

    # Отзыв по ID заказа.
    r = await client.get(f"/api/v1/control/reviews/{order_id}", headers=admin_h)
    assert r.status_code == 200
    assert r.json()["client_review"] == "Excellent service"

    # Заказ без отзыва -> 404.
    r = await client.post(
        "/api/v1/orders/requests",
        headers=owner_h,
        json={"problem_description": "no review", "house_number": 4},
    )
    no_review_request = r.json()["id"]
    r = await client.post(
        f"/api/v1/orders/requests/{no_review_request}/accept", headers=worker_h
    )
    no_review_order = r.json()["id"]
    r = await client.get(
        f"/api/v1/control/reviews/{no_review_order}", headers=admin_h
    )
    assert r.status_code == 404, ("order without review", r.status_code, r.text)


# ---------------------------------------------------------------------------
# Справочники и остатки
# ---------------------------------------------------------------------------
async def _scenario_catalogs(client, admin_h) -> int:
    # --- Техника ---
    r = await client.post(
        "/api/v1/control/technics",
        headers=admin_h,
        json={"name": "Drill", "model_params": "18V"},
    )
    assert r.status_code == 201, ("technic", r.status_code, r.text)
    technic_id = r.json()["id"]

    r = await client.get(f"/api/v1/control/technics/{technic_id}", headers=admin_h)
    assert r.status_code == 200 and r.json()["name"] == "Drill"

    r = await client.patch(
        f"/api/v1/control/technics/{technic_id}",
        headers=admin_h,
        json={"model_params": "20V"},
    )
    assert r.status_code == 200 and r.json()["model_params"] == "20V"

    r = await client.get("/api/v1/control/technics/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing technic", r.status_code, r.text)

    # --- Запчасти ---
    r = await client.post(
        "/api/v1/control/spare-parts",
        headers=admin_h,
        json={"name": "Gasket", "description": "rubber", "price": "9.99"},
    )
    assert r.status_code == 201, ("spare part", r.status_code, r.text)
    spare_part_id = r.json()["id"]

    r = await client.patch(
        f"/api/v1/control/spare-parts/{spare_part_id}",
        headers=admin_h,
        json={"price": "12.50"},
    )
    assert r.status_code == 200 and r.json()["price"] == "12.50"

    r = await client.get("/api/v1/control/spare-parts/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing spare part", r.status_code, r.text)

    # --- Склады ---
    r = await client.post(
        "/api/v1/control/warehouses",
        headers=admin_h,
        json={"name": "Main", "house_number": 1},
    )
    assert r.status_code == 201, ("warehouse", r.status_code, r.text)
    warehouse_id = r.json()["id"]

    r = await client.patch(
        f"/api/v1/control/warehouses/{warehouse_id}",
        headers=admin_h,
        json={"name": "Main-2"},
    )
    assert r.status_code == 200 and r.json()["name"] == "Main-2"

    # Несуществующая улица -> 404.
    r = await client.post(
        "/api/v1/control/warehouses",
        headers=admin_h,
        json={"name": "Bad", "street_id": 99999999},
    )
    assert r.status_code == 404, ("bad street", r.status_code, r.text)

    r = await client.get("/api/v1/control/warehouses/99999999", headers=admin_h)
    assert r.status_code == 404, ("missing warehouse", r.status_code, r.text)

    # --- Остатки ---
    r = await client.post(
        "/api/v1/control/warehouse-stocks",
        headers=admin_h,
        json={
            "warehouse_id": warehouse_id,
            "spare_part_id": spare_part_id,
            "quantity": 10,
        },
    )
    assert r.status_code == 201, ("stock", r.status_code, r.text)
    stock_id = r.json()["id"]
    assert r.json()["spare_part"]["id"] == spare_part_id
    assert r.json()["warehouse"]["id"] == warehouse_id

    # Повторная запись для той же пары -> 409.
    r = await client.post(
        "/api/v1/control/warehouse-stocks",
        headers=admin_h,
        json={
            "warehouse_id": warehouse_id,
            "spare_part_id": spare_part_id,
            "quantity": 5,
        },
    )
    assert r.status_code == 409, ("dup stock", r.status_code, r.text)

    # Несуществующий склад -> 404.
    r = await client.post(
        "/api/v1/control/warehouse-stocks",
        headers=admin_h,
        json={
            "warehouse_id": 99999999,
            "spare_part_id": spare_part_id,
            "quantity": 1,
        },
    )
    assert r.status_code == 404, ("stock bad warehouse", r.status_code, r.text)

    # Список и фильтрация.
    r = await client.get(
        "/api/v1/control/warehouse-stocks", headers=admin_h
    )
    assert r.status_code == 200 and any(s["id"] == stock_id for s in r.json())
    r = await client.get(
        "/api/v1/control/warehouse-stocks",
        headers=admin_h,
        params={"spare_part_id": spare_part_id},
    )
    assert r.status_code == 200
    assert all(s["spare_part_id"] == spare_part_id for s in r.json())

    r = await client.get(
        f"/api/v1/control/warehouses/{warehouse_id}/stocks", headers=admin_h
    )
    assert r.status_code == 200 and any(s["id"] == stock_id for s in r.json())

    # Изменение количества.
    r = await client.patch(
        f"/api/v1/control/warehouse-stocks/{stock_id}",
        headers=admin_h,
        json={"quantity": 42},
    )
    assert r.status_code == 200 and r.json()["quantity"] == 42

    # Отрицательное количество -> 400.
    r = await client.patch(
        f"/api/v1/control/warehouse-stocks/{stock_id}",
        headers=admin_h,
        json={"quantity": -1},
    )
    assert r.status_code == 422, ("negative quantity", r.status_code, r.text)

    return technic_id


# ---------------------------------------------------------------------------
# Смена статуса заявки и работника заказа
# ---------------------------------------------------------------------------
async def _scenario_status_and_worker(
    client,
    admin_h,
    owner_h,
    worker_h,
    worker_id: int,
    other_email: str,
) -> None:
    # --- Справочник статусов ---
    r = await client.get("/api/v1/control/statuses", headers=admin_h)
    assert r.status_code == 200, ("statuses", r.status_code, r.text)
    statuses = {s["name"]: s["id"] for s in r.json()}
    assert RequestStatuses.SEARCHING_MASTER in statuses
    assert RequestStatuses.CANCELLED in statuses

    # --- Смена статуса заявки ---
    r = await client.post(
        "/api/v1/orders/requests",
        headers=owner_h,
        json={"problem_description": "status admin", "house_number": 7},
    )
    assert r.status_code == 201, ("create request", r.status_code, r.text)
    request_id = r.json()["id"]
    owner_id = r.json()["user_id"]

    # Установка того же статуса — без уведомления.
    r = await client.patch(
        f"/api/v1/control/requests/{request_id}/status",
        headers=admin_h,
        json={"status_name": RequestStatuses.SEARCHING_MASTER},
    )
    assert r.status_code == 200, ("set same status", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.SEARCHING_MASTER
    assert r.json()["notification"] is None

    # Установка статуса отмены по алиасу CANCELED -> формируется уведомление.
    r = await client.patch(
        f"/api/v1/control/requests/{request_id}/status",
        headers=admin_h,
        json={"status_name": "CANCELED"},
    )
    assert r.status_code == 200, ("cancel status", r.status_code, r.text)
    body = r.json()
    assert body["status"]["name"] == RequestStatuses.CANCELLED
    note = body["notification"]
    assert note is not None, ("notification missing", body)
    assert note["type"] == "REQUEST_CANCELED"
    assert note["user_id"] == owner_id
    assert note["request_id"] == request_id
    assert note["message"]

    # Смена статуса по status_id также работает (существующий справочник).
    r = await client.patch(
        f"/api/v1/control/requests/{request_id}/status",
        headers=admin_h,
        json={"status_id": statuses[RequestStatuses.COMPLETED]},
    )
    assert r.status_code == 200, ("set by id", r.status_code, r.text)
    assert r.json()["status"]["name"] == RequestStatuses.COMPLETED
    assert r.json()["notification"] is None

    # Несуществующая заявка -> 404.
    r = await client.patch(
        "/api/v1/control/requests/99999999/status",
        headers=admin_h,
        json={"status_name": RequestStatuses.CANCELLED},
    )
    assert r.status_code == 404, ("missing request", r.status_code, r.text)

    # Несуществующий статус -> 404.
    r = await client.patch(
        f"/api/v1/control/requests/{request_id}/status",
        headers=admin_h,
        json={"status_name": "NO_SUCH_STATUS"},
    )
    assert r.status_code == 404, ("missing status", r.status_code, r.text)

    # Отсутствие параметров статуса -> 409.
    r = await client.patch(
        f"/api/v1/control/requests/{request_id}/status",
        headers=admin_h,
        json={},
    )
    assert r.status_code == 409, ("no status params", r.status_code, r.text)

    # --- Смена работника заказа ---
    r = await client.post(
        "/api/v1/orders/requests",
        headers=owner_h,
        json={"problem_description": "worker change", "house_number": 8},
    )
    assert r.status_code == 201, ("create request", r.status_code, r.text)
    order_request = r.json()["id"]
    r = await client.post(
        f"/api/v1/orders/requests/{order_request}/accept", headers=worker_h
    )
    assert r.status_code == 201, ("accept", r.status_code, r.text)
    order_id = r.json()["id"]

    # Второй работник.
    worker2_id = await _make_worker(other_email)
    assert worker2_id != worker_id

    # Замена работника: остаётся только новый.
    r = await client.put(
        f"/api/v1/control/orders/{order_id}/worker",
        headers=admin_h,
        json={"worker_id": worker2_id, "replace_existing": True},
    )
    assert r.status_code == 200, ("replace worker", r.status_code, r.text)
    ids = {w["id"] for w in r.json()["workers"]}
    assert ids == {worker2_id}, ("replace result", r.text)

    # Добавление второго работника без замены.
    r = await client.put(
        f"/api/v1/control/orders/{order_id}/worker",
        headers=admin_h,
        json={"worker_id": worker_id, "replace_existing": False},
    )
    assert r.status_code == 200, ("add worker", r.status_code, r.text)
    ids = {w["id"] for w in r.json()["workers"]}
    assert ids == {worker_id, worker2_id}, ("add result", r.text)

    # Повторное добавление того же работника не создаёт дубликат.
    r = await client.put(
        f"/api/v1/control/orders/{order_id}/worker",
        headers=admin_h,
        json={"worker_id": worker_id, "replace_existing": False},
    )
    assert r.status_code == 200
    assert len(r.json()["workers"]) == 2

    # Удаление работника из заказа.
    r = await client.delete(
        f"/api/v1/control/orders/{order_id}/worker/{worker2_id}", headers=admin_h
    )
    assert r.status_code == 200, ("remove worker", r.status_code, r.text)
    ids = {w["id"] for w in r.json()["workers"]}
    assert ids == {worker_id}, ("remove result", r.text)

    # Повторное удаление отсутствующего назначения -> 404.
    r = await client.delete(
        f"/api/v1/control/orders/{order_id}/worker/{worker2_id}", headers=admin_h
    )
    assert r.status_code == 404, ("re-remove worker", r.status_code, r.text)

    # Несуществующий работник -> 404.
    r = await client.put(
        f"/api/v1/control/orders/{order_id}/worker",
        headers=admin_h,
        json={"worker_id": 99999999},
    )
    assert r.status_code == 404, ("missing worker", r.status_code, r.text)

    # Несуществующий заказ -> 404.
    r = await client.put(
        "/api/v1/control/orders/99999999/worker",
        headers=admin_h,
        json={"worker_id": worker_id},
    )
    assert r.status_code == 404, ("missing order", r.status_code, r.text)


# ---------------------------------------------------------------------------
# Swagger
# ---------------------------------------------------------------------------
async def _scenario_swagger() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert paths["/api/v1/control/workers"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/workers"]["post"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/requests"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/orders"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/reviews"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/warehouse-stocks"]["get"]["tags"] == [TAG_ADMIN]
    assert paths["/api/v1/control/warehouses"]["post"]["tags"] == [TAG_ADMIN]

    # Ролевые группы сохранены.
    assert paths["/api/v1/orders/requests"]["get"]["tags"] == [TAG_USER]
    assert paths["/api/v1/orders/work-orders"]["get"]["tags"] == [TAG_WORKER]
    # Общие справочники остаются в группе мастера.
    assert paths["/api/v1/control/technics"]["get"]["tags"] == [TAG_WORKER]


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------
async def run_admin_flow() -> None:
    await _seed()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        suffix = uuid.uuid4().hex[:8]
        admin_email = f"adm_admin_{suffix}@example.com"
        owner_email = f"adm_owner_{suffix}@example.com"
        other_email = f"adm_other_{suffix}@example.com"
        worker_email = f"adm_worker_{suffix}@example.com"

        owner_id = await _register(client, owner_email)
        await _register(client, other_email)
        await _register(client, worker_email)
        await _register(client, admin_email, is_admin=True)
        worker_id = await _make_worker(worker_email)

        owner_h = await _login(client, owner_email)
        worker_h = await _login(client, worker_email)
        admin_h = await _login(client, admin_email)

        await _scenario_auth(client, admin_h, owner_h, worker_h)
        await _scenario_users(client, admin_h, owner_id, other_email)
        technic_id = await _scenario_catalogs(client, admin_h)
        await _scenario_workers(client, admin_h, technic_id)
        await _scenario_requests_orders(
            client, admin_h, owner_h, owner_id, worker_h, worker_id
        )
        await _scenario_status_and_worker(
            client,
            admin_h,
            owner_h,
            worker_h,
            worker_id,
            other_email,
        )
        await _scenario_swagger()

    print("ADMIN FLOW: OK")


def test_admin_flow() -> None:
    asyncio.run(run_admin_flow())


if __name__ == "__main__":
    asyncio.run(run_admin_flow())