from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ALL_STATUS_NAMES
from app.models.orders import Status


async def seed_statuses(session: AsyncSession) -> None:
    """Идемпотентно наполняет единую таблицу `statuses`.

    Статусы заявок и заказов хранятся в одной таблице `statuses`.
    Повторный запуск не создаёт дубликатов: уже существующие записи
    (по имени) пропускаются.
    """
    existing = await session.execute(select(Status.name))
    existing_names = {name for (name,) in existing.all()}
    for name in ALL_STATUS_NAMES:
        if name not in existing_names:
            session.add(Status(name=name))


async def seed_all(session: AsyncSession) -> None:
    """Идемпотентный seed справочника статусов."""
    await seed_statuses(session)
    await session.commit()