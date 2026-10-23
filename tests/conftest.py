"""Общие фикстуры/хуки тестов.

Проект использует глобальный асинхронный engine (app.core.database.engine).
Паттерн тестов — синхронные обёртки над ``asyncio.run(...)``, каждая создаёт
свой event loop. Чтобы соединения из пула, привязанные к завершившемуся loop,
не «утекали» в следующий тест, после каждого теста явно утилизируем пул в
новом короткоживущем loop.
"""

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    try:
        from app.core.database import engine
    except Exception:  # noqa: BLE001 - импорт не должен ронять тесты схем
        return

    async def _dispose() -> None:
        await engine.dispose()

    try:
        asyncio.run(_dispose())
    except Exception:  # noqa: BLE001
        pass