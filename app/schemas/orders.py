from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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