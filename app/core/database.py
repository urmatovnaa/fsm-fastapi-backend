from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings
from app.models.base import Base

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db():
    """FastAPI dependency, отдающая AsyncSession на время запроса."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise