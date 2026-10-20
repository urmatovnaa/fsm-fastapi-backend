from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import StatusNames
from app.models.orders import Status


async def seed_statuses(session: AsyncSession) -> None:
    existing = await session.execute(select(Status.name))
    existing_names = {name for (name,) in existing.all()}
    for name in StatusNames.ALL:
        if name not in existing_names:
            session.add(Status(name=name))


async def seed_all(session: AsyncSession) -> None:
    """Идемпотентный seed справочника статусов."""
    await seed_statuses(session)
    await session.commit()