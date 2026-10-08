from fastapi import APIRouter
from app.api.v1 import control, execution, planning

api_router = APIRouter()

# api_router.include_router(control.router, prefix="/control", tags=["Склад и Контроль"])
# api_router.include_router(execution.router, prefix="/execution", tags=["Наряды мастера"])
# api_router.include_router(planning.router, prefix="/planning", tags=["Планирование и Слоты"])