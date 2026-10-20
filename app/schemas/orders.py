from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(from_attributes=True)