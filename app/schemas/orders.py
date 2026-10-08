from pydantic import BaseModel, ConfigDict

from app.models.orders import OrderStatus


class RequestCreate(BaseModel):
    street_id: int
    house_number: int
    problem_description: str


class RequestResponse(BaseModel):
    id: int
    user_id: int
    status: OrderStatus
    street_id: int
    house_number: int
    problem_description: str

    model_config = ConfigDict(from_attributes=True)


class WorkOrderResponse(BaseModel):
    id: int
    request_id: int
    worker_id: int

    model_config = ConfigDict(from_attributes=True)