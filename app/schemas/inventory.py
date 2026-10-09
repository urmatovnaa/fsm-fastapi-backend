from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TechniqueResponse(BaseModel):
    id: int
    name: str | None = None
    model_parameters: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseResponse(BaseModel):
    id: int
    name: str | None = None
    street_id: int | None = None
    house_number: int | None = None

    model_config = ConfigDict(from_attributes=True)


class SparePartResponse(BaseModel):
    id: int
    name: str | None = None
    type: str | None = None
    description: str | None = None
    price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseInventoryResponse(BaseModel):
    warehouse_id: int
    spare_part_id: int

    model_config = ConfigDict(from_attributes=True)