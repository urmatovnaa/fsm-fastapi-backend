from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StatusResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class StreetResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class RequestCreate(BaseModel):
    street_id: int | None = None
    house_number: int | None = None
    latitude: int | None = None
    longitude: int | None = None
    problem_description: str | None = None
    urgency: int | None = None
    visit_date: date | None = None
    visit_time_start: time | None = None
    visit_time_end: time | None = None


class OrderPartCreate(BaseModel):
    """Позиция запчасти, использованной при выполнении заказа.

    Складского учёта нет — фиксируется только факт использования:
    ссылка на запчасть и количество.
    """

    spare_part_id: int | None = None
    quantity: int = Field(gt=0)


class OrderPartResponse(BaseModel):
    id: int
    order_id: int
    spare_part_id: int | None = None
    spare_part_name: str | None = None
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class OrderPhotoCreate(BaseModel):
    """Фотография результата, привязанная к заказу."""

    photo_url: str
    photo_type: bool | None = None


class OrderPhotoResponse(BaseModel):
    id: int
    order_id: int
    photo_url: str
    photo_type: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderReportUpdate(BaseModel):
    """Отчёт мастера о выполненной работе (все поля необязательны)."""

    checklist: str | None = None
    work_description: str | None = None
    total_amount: Decimal | None = None


class ClientReviewCreate(BaseModel):
    """Отзыв клиента о выполненной работе."""

    client_review: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Вложенные схемы
# ---------------------------------------------------------------------------
class OrderSummary(BaseModel):
    """Краткая карточка заказа для вложения в ответ заявки."""

    id: int
    request_id: int
    status_id: int | None = None
    status: StatusResponse | None = None
    work_start_time: datetime | None = None
    work_end_time: datetime | None = None
    total_amount: Decimal | None = None
    client_review: str | None = None
    work_description: str | None = None
    checklist: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RequestSummary(BaseModel):
    """Краткая карточка заявки для вложения в ответ заказа."""

    id: int
    status_id: int | None = None
    status: StatusResponse | None = None
    street_id: int | None = None
    house_number: int | None = None
    latitude: int | None = None
    longitude: int | None = None
    problem_description: str | None = None
    urgency: int | None = None
    visit_date: date | None = None
    visit_time_start: time | None = None
    visit_time_end: time | None = None

    model_config = ConfigDict(from_attributes=True)


class RequestResponse(BaseModel):
    id: int
    user_id: int
    status_id: int | None = None
    status: StatusResponse | None = None
    street_id: int | None = None
    house_number: int | None = None
    latitude: int | None = None
    longitude: int | None = None
    problem_description: str | None = None
    urgency: int | None = None
    visit_date: date | None = None
    visit_time_start: time | None = None
    visit_time_end: time | None = None
    created_at: datetime
    # Связанные заказы (для отслеживания статуса заказа клиентом).
    orders: list[OrderSummary] = []

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    request_id: int
    status_id: int | None = None
    status: StatusResponse | None = None
    priority: int | None = None
    appointment_time: datetime | None = None
    work_start_time: datetime | None = None
    work_end_time: datetime | None = None
    checklist: str | None = None
    work_description: str | None = None
    total_amount: Decimal | None = None
    client_review: str | None = None
    worker_review: str | None = None
    # Связанные данные исходной заявки.
    request: RequestSummary | None = None
    # Проверка/результат работы.
    parts: list[OrderPartResponse] = []
    photos: list[OrderPhotoResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Административные схемы: заявки, заказы и отзывы
# ---------------------------------------------------------------------------
class AdminRequestUser(BaseModel):
    """Пользователь, создавший заявку (без чувствительных данных)."""

    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminWorkerRef(BaseModel):
    """Назначенный работник (для отображения в заказе)."""

    id: int
    user_id: int
    full_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminOrderResponse(OrderResponse):
    """Заказ с раскрытыми назначенными работниками."""

    workers: list[AdminWorkerRef] = []


class AdminRequestDetailResponse(RequestResponse):
    """Полная карточка заявки для администратора.

    Содержит владельца заявки, статус, адрес/координаты, описание, срочность,
    связанные заказы и назначенных работников.
    """

    user: AdminRequestUser | None = None
    orders: list[AdminOrderResponse] = []


class ReviewResponse(BaseModel):
    """Отзыв клиента по заказу (``Order.client_review``)."""

    order_id: int
    request_id: int
    user_id: int | None = None
    user_full_name: str | None = None
    client_review: str
    total_amount: Decimal | None = None
    work_description: str | None = None
    work_end_time: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Административные схемы: смена статуса заявки и работника заказа
# ---------------------------------------------------------------------------
class RequestStatusUpdate(BaseModel):
    """Смена статуса заявки администратором.

    Статус выбирается из существующего справочника ``Status``: можно передать
    ``status_id`` (ID записи) или ``status_name`` (имя, например ``CANCELED``).
    Новая система статусов не создаётся — используется существующая модель.
    """

    status_id: int | None = None
    status_name: str | None = None


class NotificationResponse(BaseModel):
    """Уведомление о смене статуса заявки.

    Реальная система уведомлений не подключена: уведомление формируется как
    JSON-ответ и не сохраняется в БД (отдельная таблица не создаётся).
    """

    type: str
    user_id: int
    request_id: int
    message: str


class AdminRequestStatusResponse(AdminRequestDetailResponse):
    """Результат смены статуса заявки для администратора."""

    # Уведомление пользователю заполняется при переводе заявки в CANCELED.
    notification: NotificationResponse | None = None


class OrderWorkerChange(BaseModel):
    """Назначение/замена работника, привязанного к заказу.

    Используется существующая связь ``OrderWorker`` — новая таблица и поле не
    создаются. Если ``replace_existing`` истинно, текущие работники заказа
    заменяются; иначе работник добавляется дополнительно.
    """

    worker_id: int
    replace_existing: bool = True


class OrderWorkerResponse(AdminOrderResponse):
    """Результат изменения работников заказа для администратора."""