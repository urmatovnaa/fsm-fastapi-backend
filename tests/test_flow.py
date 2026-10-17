"""End-to-end integration test: register -> login -> create request -> accept -> complete.

Запускается поверх реального приложения и PostgreSQL (без моков).
Требует запущенный PostgreSQL и применённые миграции.
"""
import asyncio
import uuid

import httpx

from app.main import app


async def run_flow() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        suffix = uuid.uuid4().hex[:8]

        user_email = f"user_{suffix}@example.com"
        worker_email = f"worker_{suffix}@example.com"
        password = "secret123"

        # 1. Регистрация клиента
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Ivan Client",
                "email": user_email,
                "password": password,
                "role": "USER",
            },
        )
        assert r.status_code == 201, ("register user", r.status_code, r.text)
        assert "password" not in r.json()

        # 2. Регистрация воркера (авто-создание Worker)
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Petr Worker",
                "email": worker_email,
                "password": password,
                "role": "WORKER",
            },
        )
        assert r.status_code == 201, ("register worker", r.status_code, r.text)

        # 3. Логин клиента -> JWT
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": user_email, "password": password},
        )
        assert r.status_code == 200, ("login user", r.status_code, r.text)
        user_token = r.json()["access_token"]

        # 4. Логин воркера -> JWT
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": worker_email, "password": password},
        )
        assert r.status_code == 200, ("login worker", r.status_code, r.text)
        worker_token = r.json()["access_token"]

        user_headers = {"Authorization": f"Bearer {user_token}"}
        worker_headers = {"Authorization": f"Bearer {worker_token}"}

        # 5. /me
        r = await client.get("/api/v1/auth/me", headers=user_headers)
        assert r.status_code == 200, ("me", r.status_code, r.text)
        assert r.json()["email"] == user_email

        # 6. Неверный токен -> 401
        r = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}
        )
        assert r.status_code == 401, ("bad token", r.status_code, r.text)

        # 7. Создание заявки клиентом (user_id берётся из токена)
        r = await client.post(
            "/api/v1/orders/requests",
            headers=user_headers,
            json={
                "problem_description": "Water leak",
                "house_number": 12,
                "urgency_level": 2,
            },
        )
        assert r.status_code == 201, ("create request", r.status_code, r.text)
        request_id = r.json()["id"]
        assert r.json()["status"]["name"] == "NEW"

        # 8. Клиент не может принять заявку -> 403
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=user_headers
        )
        assert r.status_code == 403, ("user accept forbidden", r.status_code, r.text)

        # 9. Воркер принимает заявку -> создаётся order
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=worker_headers
        )
        assert r.status_code == 201, ("accept request", r.status_code, r.text)
        order_id = r.json()["id"]

        # 10. Повторный accept -> 409 (уже не NEW)
        r = await client.post(
            f"/api/v1/orders/requests/{request_id}/accept", headers=worker_headers
        )
        assert r.status_code == 409, ("double accept", r.status_code, r.text)

        # 11. Завершение заказа воркером -> request DONE
        r = await client.post(
            f"/api/v1/orders/work-orders/{order_id}/complete", headers=worker_headers
        )
        assert r.status_code == 200, ("complete order", r.status_code, r.text)
        assert r.json()["work_end_time"] is not None

        # 12. Статус заявки теперь DONE
        r = await client.get(
            f"/api/v1/orders/requests/{request_id}", headers=user_headers
        )
        assert r.status_code == 200, ("get request", r.status_code, r.text)
        assert r.json()["status"]["name"] == "DONE"

        print("INTEGRATION FLOW: OK")
        print(f"user_id={r.json()['user_id']} request_id={request_id} order_id={order_id}")


if __name__ == "__main__":
    asyncio.run(run_flow())