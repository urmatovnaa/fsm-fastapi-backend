from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StatusResponse(BaseModel):
    id: int
    name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StreetResponse(BaseModel):
    id: int
    name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OperationResponse(BaseModel):
    id: int
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class RequestCreate(BaseModel):
    street_id: int | None = None
    house_number: int | None = None
    problem_description: str | None = None
    urgency_level: int | None = None
    longitude: int | None = None
    latitude: int | None = None
    arrival_at: datetime | None = None


class RequestResponse(BaseModel):
    id: int
    user_id: int | None = None
    status_id: int | None = None
    status: StatusResponse | None = None
    street_id: int | None = None
    house_number: int | None = None
    urgency_level: int | None = None
    problem_description: str | None = None
    longitude: int | None = None
    latitude: int | None = None
    created_at: datetime | None = None
    arrival_at: datetime | None = None
    estimated_price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    request_id: int | None = None
    worker_id: int | None = None
    appointment_time: datetime | None = None
    work_start_time: datetime | None = None
    work_end_time: datetime | None = None
    work_description: str | None = None
    total_amount: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)