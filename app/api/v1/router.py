from fastapi import APIRouter

from app.api.v1 import admin, auth, control, planning, user, worker

api_router = APIRouter()

# Порядок включения соответствует логике ролей: клиент -> мастер ->
# администратор -> служебные модули -> аутентификация.
api_router.include_router(user.router)
api_router.include_router(worker.router)
api_router.include_router(control.router)
api_router.include_router(admin.router)
api_router.include_router(planning.router)
api_router.include_router(auth.router)