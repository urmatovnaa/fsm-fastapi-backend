from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TechnicCreate(BaseModel):
    name: str
    model_params: str | None = None


class TechnicResponse(BaseModel):
    id: int
    name: str
    model_params: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseResponse(BaseModel):
    id: int
    name: str
    street_id: int | None = None
    house_number: int | None = None

    model_config = ConfigDict(from_attributes=True)


class SparePartCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal | None = None


class SparePartResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseStockResponse(BaseModel):
    id: int
    warehouse_id: int
    spare_part_id: int
    quantity: int

    model_config = ConfigDict(from_attributes=True)