"""End-to-end integration test for the new MasterFlow data structure.

Raw flow: register (user/worker/admin) -> login -> create request
-> (worker) accept -> complete, with role-based access checks.

Запускается поверх реального приложения и PostgreSQL (без моков).
Требует запущенный PostgreSQL и применённые миграции + seed.

Запуск напрямую:
    python -m tests.test_flow
Запуск через pytest:
    pytest tests/test_flow.py
"""
import asyncio
import uuid

import httpx

from app.main import app


async def run_flow() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        suffix = uuid.uuid4().hex[:8]
        password = "secret123"

        user_email = f"user_{suffix}@example.com"
        worker_email = f"worker_{suffix}@example.com"
        admin_email = f"admin_{suffix}@example.com"

        # 0. Валидация password_confirmation (не требует записи в БД)
        # 0a. Несовпадающие пароли -> 422
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Bad Pass",
                "email": f"bad_{suffix}@example.com",
                "password": password,
                "password_confirmation": "different_password",
            },
        )
        assert r.status_code == 422, ("mismatch password", r.status_code, r.text)
        assert "match" in r.text.lower(), r.text

        # 0b. Отсутствует password_confirmation -> 422 (обязательное поле)
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "No Confirmation",
                "email": f"noconf_{suffix}@example.com",
                "password": password,
            },
        )
        assert r.status_code == 422, ("missing confirmation", r.status_code, r.text)

        # 1. Регистрация клиента
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Ivan Client",
                "email": user_email,
                "password": password,
                "password_confirmation": password,
            },
        )
        assert r.status_code == 201, ("register user", r.status_code, r.text)
        assert "password" not in r.json()
        assert r.json()["is_admin"] is False

        # 2. Регистрация воркера (без роли — просто пользователь)
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Petr Worker",
                "email": worker_email,
                "password": password,
                "password_confirmation": password,
            },
        )
        assert r.status_code == 201, ("register worker", r.status_code, r.text)

        # 3. Регистрация администратора
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Ada Admin",
                "email": admin_email,
                "password": password,
                "password_confirmation": password,
                "is_admin": True,
            },
        )
        assert r.status_code == 201, ("register admin", r.status_code, r.text)
        assert r.json()["is_admin"] is True

        # 4. Повторная регистрация -> 409
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Ivan Client",
                "email": user_email,
                "password": password,
                "password_confirmation": password,
            },
        )
        assert r.status_code == 409, ("duplicate register", r.status_code, r.text)

        # 5. Логин всех -> JWT
        async def login(email: str) -> str:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            assert resp.status_code == 200, ("login", email, resp.status_code, resp.text)
            return resp.json()["access_token"]

        user_token = await login(user_email)
        worker_token = await login(worker_email)
        admin_token = await login(admin_email)

        # 6. Неверный пароль -> 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": user_email, "password": "wrong"},
        )
        assert r.status_code == 401, ("bad login", r.status_code, r.text)

        user_headers = {"Authorization": f"Bearer {user_token}"}
        worker_headers = {"Authorization": f"Bearer {worker_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 7. /me
        r = await client.get("/api/v1/auth/me", headers=user_headers)
        assert r.status_code == 200, ("me", r.status_code, r.text)
        assert r.json()["email"] == user_email

        # 8. Неверный токен -> 401
        r = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}
        )
        assert r.status_code == 401, ("bad token", r.status_code, r.text)

        # 9. Создание заявки клиентом (user_id берётся из токена)
        r = await client.post(
            "/api/v1/orders/requests",
            headers=user_headers,
            json={
                "problem_description": "Water leak",
                "house_number": 12,
                "urgency": 2,
            },
        )
        assert r.status_code == 201, ("create request", r.status_code, r.text)
        request_id = r.json()["id"]
        assert r.json()["status"]["name"] == "SEARCHING_MASTER"
        assert r.json()["urgency"] == 2

        # 10. Admin-only: создание техники. Клиент -> 403.
        r = await client.post(
            "/api/v1/control/technics",
            headers=user_headers,
            json={"name": "Drill", "model_params": "18V"},
        )
        assert r.status_code == 403, ("non-admin technic", r.status_code, r.text)

        r = await client.post(
            "/api/v1/control/technics",
            headers=admin_headers,
            json={"name": "Drill", "model_params": "18V"},
        )
        assert r.status_code == 201, ("admin technic", r.status_code, r.text)
        assert r.json()["model_params"] == "18V"

        # 11. Admin-only: создание запчасти.
        r = await client.post(
            "/api/v1/control/spare-parts",
            headers=admin_headers,
            json={"name": "Gasket", "description": "rubber", "price": "9.99"},
        )
        assert r.status_code == 201, ("admin spare part", r.status_code, r.text)
        assert r.json()["name"] == "Gasket"

        # 12. Клиент не может принять заявку -> 403 (нет профиля мастера)
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=user_headers
        )
        assert r.status_code == 403, ("user accept forbidden", r.status_code, r.text)

        # 13. Несуществующая заявка -> 404
        r = await client.post(
            "/api/v1/orders/requests/999999/accept", headers=worker_headers
        )
        assert r.status_code == 403, ("worker without profile", r.status_code, r.text)

        # --- Назначаем воркеру профиль Worker напрямую через БД ---
        from app.core.database import AsyncSessionLocal
        from app.models.users import Worker
        from app.services import users as user_service

        async with AsyncSessionLocal() as session:
            wk_user = await user_service.get_user_by_email(session, worker_email)
            session.add(Worker(user_id=wk_user.id))
            await session.commit()

        # 14. Воркер принимает заявку -> создаётся order со статусом ACCEPTED
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=worker_headers
        )
        assert r.status_code == 201, ("accept request", r.status_code, r.text)
        order_id = r.json()["id"]
        assert r.json()["status"]["name"] == "ACCEPTED"

        # 15. Повторный accept -> 409 (уже есть активный заказ)
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=worker_headers
        )
        assert r.status_code == 409, ("double accept", r.status_code, r.text)

        # 16. Список заказов воркера содержит созданный order
        r = await client.get("/api/v1/orders/work-orders", headers=worker_headers)
        assert r.status_code == 200, ("list work orders", r.status_code, r.text)
        assert any(o["id"] == order_id for o in r.json())

        # 16b. Недопустимый переход: complete из ACCEPTED -> 409
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_headers
        )
        assert r.status_code == 409, ("invalid complete", r.status_code, r.text)

        # 16c. ACCEPTED -> EN_ROUTE
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/en-route", headers=worker_headers
        )
        assert r.status_code == 200, ("en route", r.status_code, r.text)
        assert r.json()["status"]["name"] == "EN_ROUTE"

        # 16d. EN_ROUTE -> IN_PROGRESS
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/start", headers=worker_headers
        )
        assert r.status_code == 200, ("start work", r.status_code, r.text)
        assert r.json()["status"]["name"] == "IN_PROGRESS"

        # 17. Завершение заказа воркером -> order COMPLETED, request COMPLETED
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_headers
        )
        assert r.status_code == 200, ("complete order", r.status_code, r.text)
        assert r.json()["work_end_time"] is not None
        assert r.json()["status"]["name"] == "COMPLETED"

        # 18. Статус заявки теперь COMPLETED
        r = await client.get(
            f"/api/v1/orders/requests/{request_id}", headers=user_headers
        )
        assert r.status_code == 200, ("get request", r.status_code, r.text)
        assert r.json()["status"]["name"] == "COMPLETED"

        # 18b. Терминальный заказ: повторный complete -> 409
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_headers
        )
        assert r.status_code == 409, ("terminal complete", r.status_code, r.text)

        # 19. Планирование (защищённый модуль)
        r = await client.get("/api/v1/planning/health", headers=user_headers)
        assert r.status_code == 200, ("planning health", r.status_code, r.text)

        print("INTEGRATION FLOW: OK")
        print(f"request_id={request_id} order_id={order_id}")


def test_flow() -> None:
    """pytest-обёртка."""
    asyncio.run(run_flow())


if __name__ == "__main__":
    asyncio.run(run_flow())