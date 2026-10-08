from fastapi import FastAPI
from app.api.v1.router import api_router

app = FastAPI(
    title="MasterFlow API",
    description="Система управления выездным сервисом и распределения заказов",
    version="1.0.0"
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "MasterFlow API успешно запущен!"}