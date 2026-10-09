"""Запуск seed-данных вручную: python -m app.scripts.seed"""

import asyncio

from app.core.database import AsyncSessionLocal
from app.services.seed import seed_all


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed_all(session)
    print("Seed completed")


if __name__ == "__main__":
    asyncio.run(main())