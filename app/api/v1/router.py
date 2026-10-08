from fastapi import APIRouter
from app.api.v1 import auth, execution

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(execution.router)