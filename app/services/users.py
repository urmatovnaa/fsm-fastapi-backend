from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import RoleNames
from app.core.security import hash_password
from app.models.users import Role, User, Worker


class UserAlreadyExists(Exception):
    ...


class RoleNotFound(Exception):
    ...


async def get_role_by_name(session: AsyncSession, name: str) -> Role | None:
    result = await session.execute(select(Role).where(Role.name == name))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User).options(selectinload(User.role)).where(User.email == email)
    )
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
    role_name: str = RoleNames.USER,
) -> User:
    existing = await get_user_by_email(session, email)
    if existing is not None:
        raise UserAlreadyExists

    role = await get_role_by_name(session, role_name)
    if role is None:
        raise RoleNotFound

    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        password=hash_password(password),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()

    # Для роли WORKER автоматически создаём профиль Worker.
    if role_name == RoleNames.WORKER:
        session.add(Worker(user_id=user.id))

    await session.commit()
    await session.refresh(user, attribute_names=["role"])
    return user