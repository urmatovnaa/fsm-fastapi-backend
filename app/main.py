import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.database import AsyncSessionLocal
from app.services.seed import seed_all

logger = logging.getLogger("masterflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Идемпотентный seed ролей/статусов при старте.
    try:
        async with AsyncSessionLocal() as session:
            await seed_all(session)
        logger.info("Seed completed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Seed skipped: %s", exc)

    yield


app = FastAPI(
    title="MasterFlow API",
    description="Система управления выездным сервисом и распределения заказов",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "MasterFlow API успешно запущен!"}