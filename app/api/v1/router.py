from fastapi import APIRouter

from app.api.v1 import auth, control, execution, planning

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(execution.router)
api_router.include_router(control.router)
api_router.include_router(planning.router)