from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.tags import TAG_WORKER
from app.models.users import User

router = APIRouter(prefix="/planning", tags=[TAG_WORKER])


@router.get("/health")
async def planning_health(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Заготовка модуля планирования.

    Использует те же database/session conventions, что и остальные модули.
    """
    return {"status": "ok", "module": "planning"}