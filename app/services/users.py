from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.users import User, Worker


class UserAlreadyExists(Exception):
    ...


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_worker_by_user_id(session: AsyncSession, user_id: int) -> Worker | None:
    result = await session.execute(select(Worker).where(Worker.user_id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    full_name: str,
    email: str,
    password: str,
    phone: str | None = None,
    is_admin: bool = False,
) -> User:
    existing = await get_user_by_email(session, email)
    if existing is not None:
        raise UserAlreadyExists

    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        password=hash_password(password),
        is_admin=is_admin,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user