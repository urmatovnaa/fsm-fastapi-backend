from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleNames, StatusNames
from app.models.orders import Status
from app.models.users import Role


async def seed_roles(session: AsyncSession) -> None:
    existing = await session.execute(select(Role.name))
    existing_names = {name for (name,) in existing.all()}
    for name in RoleNames.ALL:
        if name not in existing_names:
            session.add(Role(name=name))


async def seed_statuses(session: AsyncSession) -> None:
    existing = await session.execute(select(Status.name))
    existing_names = {name for (name,) in existing.all()}
    for name in StatusNames.ALL:
        if name not in existing_names:
            session.add(Status(name=name))


async def seed_all(session: AsyncSession) -> None:
    """Идемпотентный seed ролей и статусов."""
    await seed_roles(session)
    await seed_statuses(session)
    await session.commit()