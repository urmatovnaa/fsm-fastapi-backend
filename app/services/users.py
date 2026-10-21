from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.inventory import Technic
from app.models.orders import Order, OrderWorker, Schedule, Status
from app.models.users import Skill, User, Worker

# Терминальные статусы заказов (для расчёта загрузки работника).
_TERMINAL_ORDER_STATUSES = ("COMPLETED", "NOT_COMPLETED", "CANCELLED")


class UserAlreadyExists(Exception):
    ...


class WorkerNotFound(Exception):
    ...


class WorkerAlreadyExists(Exception):
    """У пользователя уже есть профиль работника."""


class WorkerEmailConflict(Exception):
    """Email нового работника уже занят (нарушение уникальности)."""


class TechnicNotFound(Exception):
    ...


class SkillNotFound(Exception):
    ...


class ScheduleNotFound(Exception):
    ...


class InvalidSchedule(Exception):
    """Некорректный интервал расписания или недоступная связь с нарядом."""


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_detail(session: AsyncSession, user_id: int) -> User | None:
    """Пользователь с предзагруженным профилем работника (без lazy-load)."""
    result = await session.execute(
        select(User)
        .options(selectinload(User.worker_profile))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_worker_by_user_id(session: AsyncSession, user_id: int) -> Worker | None:
    result = await session.execute(select(Worker).where(Worker.user_id == user_id))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    """Все пользователи с предзагруженным профилем мастера (для админа)."""
    result = await session.execute(
        select(User).options(selectinload(User.worker_profile)).order_by(User.id)
    )
    return list(result.scalars().all())


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


# ---------------------------------------------------------------------------
# Административное управление пользователями
# ---------------------------------------------------------------------------
async def update_user(
    session: AsyncSession,
    *,
    user: User,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> User:
    """Обновляет разрешённые поля пользователя.

    Массовое присваивание запрещено: обновляются только full_name/email/phone.
    Пароль и is_admin здесь изменить нельзя. При занятом email — конфликт.
    """
    if email is not None and email != user.email:
        existing = await get_user_by_email(session, email)
        if existing is not None and existing.id != user.id:
            raise UserAlreadyExists

    if full_name is not None:
        user.full_name = full_name
    if email is not None:
        user.email = email
    if phone is not None:
        user.phone = phone

    await session.commit()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Административное управление работниками
# ---------------------------------------------------------------------------
async def list_workers(session: AsyncSession) -> list[Worker]:
    """Все работники с предзагруженным пользователем (без N+1)."""
    result = await session.execute(
        select(Worker)
        .options(selectinload(Worker.user))
        .order_by(Worker.id)
    )
    return list(result.scalars().all())


async def get_worker_by_id(session: AsyncSession, worker_id: int) -> Worker | None:
    result = await session.execute(
        select(Worker).where(Worker.id == worker_id)
    )
    return result.scalar_one_or_none()


async def get_worker_detail(session: AsyncSession, worker_id: int) -> Worker | None:
    """Работник со связями user/skills(+technic)/schedules/orders(+status)."""
    result = await session.execute(
        select(Worker)
        .options(
            selectinload(Worker.user),
            selectinload(Worker.skills).selectinload(Skill.technic),
            selectinload(Worker.schedules),
            selectinload(Worker.orders)
            .selectinload(OrderWorker.order)
            .selectinload(Order.status),
        )
        .where(Worker.id == worker_id)
    )
    return result.scalar_one_or_none()


async def count_worker_active_orders(session: AsyncSession, worker_id: int) -> int:
    """Загрузка работника: число незавершённых (активных) нарядов.

    Расчёт формируется сервисом из существующих данных (OrderWorker/Order/
    Status), без новых таблиц и полей. Активным считается наряд, статус
    которого не входит в терминальный набор.
    """
    result = await session.execute(
        select(func.count(Order.id))
        .join(OrderWorker, OrderWorker.order_id == Order.id)
        .join(Status, Status.id == Order.status_id)
        .where(
            OrderWorker.worker_id == worker_id,
            Status.name.notin_(_TERMINAL_ORDER_STATUSES),
        )
    )
    return int(result.scalar_one())


async def create_worker_with_user(
    session: AsyncSession,
    *,
    full_name: str,
    email: str,
    password: str,
    phone: str | None = None,
    experience: int | None = None,
    latitude: int | None = None,
    longitude: int | None = None,
) -> Worker:
    """Создаёт нового пользователя и связанный профиль работника.

    Операция атомарна: User и Worker создаются в одной транзакции. При любой
    ошибке (например, конфликт email) — полный откат, чтобы не осталось
    пользователя без профиля работника.
    """
    if await get_user_by_email(session, email) is not None:
        raise WorkerEmailConflict(email)

    try:
        user = User(
            full_name=full_name,
            email=email,
            phone=phone,
            password=hash_password(password),
            is_admin=False,
        )
        session.add(user)
        await session.flush()

        worker = Worker(
            user_id=user.id,
            experience=experience,
            latitude=latitude,
            longitude=longitude,
        )
        session.add(worker)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise WorkerEmailConflict(email)
    except Exception:
        await session.rollback()
        raise

    await session.refresh(worker)
    return worker


async def update_worker(
    session: AsyncSession,
    *,
    worker: Worker,
    experience: int | None = None,
    latitude: int | None = None,
    longitude: int | None = None,
) -> Worker:
    """Обновляет разрешённые поля профиля работника."""
    if experience is not None:
        worker.experience = experience
    if latitude is not None:
        worker.latitude = latitude
    if longitude is not None:
        worker.longitude = longitude
    await session.commit()
    await session.refresh(worker)
    return worker


# ---------------------------------------------------------------------------
# Навыки работника
# ---------------------------------------------------------------------------
async def list_worker_skills(session: AsyncSession, worker_id: int) -> list[Skill]:
    result = await session.execute(
        select(Skill)
        .options(selectinload(Skill.technic))
        .where(Skill.worker_id == worker_id)
        .order_by(Skill.id)
    )
    return list(result.scalars().all())


async def add_worker_skill(
    session: AsyncSession, *, worker_id: int, technic_id: int | None
) -> Skill:
    """Добавляет навык работнику.

    Проверяет существование работника и (при указании) техники. Повторное
    добавление такой же связи (worker_id, technic_id) не создаёт дубликат —
    возвращается существующая запись.
    """
    worker = await get_worker_by_id(session, worker_id)
    if worker is None:
        raise WorkerNotFound(worker_id)

    if technic_id is not None:
        technic = await session.get(Technic, technic_id)
        if technic is None:
            raise TechnicNotFound(technic_id)

    existing = await session.execute(
        select(Skill).where(
            Skill.worker_id == worker_id,
            Skill.technic_id == technic_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is None:
        skill = Skill(worker_id=worker_id, technic_id=technic_id)
        session.add(skill)
        await session.commit()
        skill_id = skill.id
    else:
        skill_id = found.id

    # Всегда возвращаем навык с предзагруженной техникой (без lazy-load).
    result = await session.execute(
        select(Skill).options(selectinload(Skill.technic)).where(Skill.id == skill_id)
    )
    return result.scalar_one()


async def delete_worker_skill(
    session: AsyncSession, *, worker_id: int, skill_id: int
) -> None:
    result = await session.execute(
        select(Skill).where(Skill.id == skill_id, Skill.worker_id == worker_id)
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise SkillNotFound(skill_id)
    await session.delete(skill)
    await session.commit()


# ---------------------------------------------------------------------------
# Расписание работника
# ---------------------------------------------------------------------------
async def list_worker_schedules(
    session: AsyncSession, worker_id: int
) -> list[Schedule]:
    result = await session.execute(
        select(Schedule)
        .where(Schedule.worker_id == worker_id)
        .order_by(Schedule.id)
    )
    return list(result.scalars().all())


async def create_schedule(
    session: AsyncSession,
    *,
    worker_id: int,
    start_time,
    end_time,
    order_id: int | None = None,
) -> Schedule:
    """Создаёт запись расписания с проверкой интервала и связей."""
    worker = await get_worker_by_id(session, worker_id)
    if worker is None:
        raise WorkerNotFound(worker_id)
    if start_time >= end_time:
        raise InvalidSchedule("start_time must be before end_time")
    if order_id is not None:
        order = await session.get(Order, order_id)
        if order is None:
            raise InvalidSchedule("order not found")

    schedule = Schedule(
        worker_id=worker_id,
        start_time=start_time,
        end_time=end_time,
        order_id=order_id,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def update_schedule(
    session: AsyncSession,
    *,
    schedule_id: int,
    start_time=None,
    end_time=None,
    order_id: int | None = None,
    order_id_provided: bool = False,
) -> Schedule:
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ScheduleNotFound(schedule_id)

    new_start = start_time if start_time is not None else schedule.start_time
    new_end = end_time if end_time is not None else schedule.end_time
    if new_start >= new_end:
        raise InvalidSchedule("start_time must be before end_time")

    if order_id_provided:
        if order_id is not None:
            order = await session.get(Order, order_id)
            if order is None:
                raise InvalidSchedule("order not found")
        schedule.order_id = order_id

    schedule.start_time = new_start
    schedule.end_time = new_end
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def delete_schedule(session: AsyncSession, *, schedule_id: int) -> None:
    result = await session.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ScheduleNotFound(schedule_id)
    await session.delete(schedule)
    await session.commit()