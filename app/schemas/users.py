from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.inventory import TechnicResponse
from app.schemas.orders import OrderSummary


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str
    password_confirmation: str
    is_admin: bool = False

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "UserCreate":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(BaseModel):
    """Пользователь с вычисленной ролью (для админского листинга)."""

    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    is_admin: bool = False
    worker_id: int | None = None
    role: str = "user"

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def resolve_role(self) -> "AdminUserResponse":
        if self.is_admin:
            self.role = "admin"
        elif self.worker_id is not None:
            self.role = "worker"
        else:
            self.role = "user"
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Административные схемы: пользователи и работники
# ---------------------------------------------------------------------------
class UserUpdate(BaseModel):
    """Редактирование пользователя администратором (все поля необязательны).

    Пароль и флаг ``is_admin`` намеренно недоступны: привилегии нельзя
    повысить через массовое обновление, а пароль меняется отдельным сценарием.
    """

    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None


class AdminUserDetailResponse(AdminUserResponse):
    """Подробная карточка пользователя для администратора."""


class SkillCreate(BaseModel):
    technic_id: int | None = None


class SkillResponse(BaseModel):
    id: int
    worker_id: int
    technic_id: int | None = None
    technic: TechnicResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class ScheduleCreate(BaseModel):
    start_time: time
    end_time: time
    order_id: int | None = None


class ScheduleUpdate(BaseModel):
    """Обновление записи расписания (все поля необязательны)."""

    start_time: time | None = None
    end_time: time | None = None
    order_id: int | None = None


class ScheduleResponse(BaseModel):
    id: int
    worker_id: int
    start_time: time
    end_time: time
    order_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkerCreate(BaseModel):
    """Создание работника вместе с новым профилем пользователя.

    Создаются две связанные записи (User + Worker) в одной транзакции.
    Пароль хешируется существующими средствами проекта.
    """

    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str = Field(min_length=1)
    experience: int | None = None
    latitude: int | None = None
    longitude: int | None = None


class WorkerUpdate(BaseModel):
    """Редактирование профиля работника (все поля необязательны)."""

    experience: int | None = None
    latitude: int | None = None
    longitude: int | None = None


class WorkerUserInfo(BaseModel):
    """Данные связанного пользователя работника."""

    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkerSummary(BaseModel):
    """Краткая карточка работника (для списка)."""

    id: int
    user_id: int
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    experience: int | None = None
    latitude: int | None = None
    longitude: int | None = None


class WorkerOrderInfo(BaseModel):
    """Наряд работника с раскрытым статусом."""

    id: int
    request_id: int
    status_id: int | None = None
    status_name: str | None = None
    appointment_time: datetime | None = None
    work_start_time: datetime | None = None
    work_end_time: datetime | None = None


class WorkerDetailResponse(BaseModel):
    """Полная карточка работника с навыками, расписанием и нарядами."""

    id: int
    user_id: int
    experience: int | None = None
    latitude: int | None = None
    longitude: int | None = None
    user: WorkerUserInfo | None = None
    skills: list[SkillResponse] = []
    schedules: list[ScheduleResponse] = []
    orders: list[OrderSummary] = []
    workload: int = 0