from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TechnicCreate(BaseModel):
    name: str
    model_params: str | None = None


class TechnicUpdate(BaseModel):
    """Обновление техники (все поля необязательны)."""

    name: str | None = None
    model_params: str | None = None


class TechnicResponse(BaseModel):
    id: int
    name: str
    model_params: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseCreate(BaseModel):
    name: str
    street_id: int | None = None
    house_number: int | None = None


class WarehouseUpdate(BaseModel):
    """Обновление склада (все поля необязательны)."""

    name: str | None = None
    street_id: int | None = None
    house_number: int | None = None


class StreetResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class WarehouseResponse(BaseModel):
    id: int
    name: str
    street_id: int | None = None
    house_number: int | None = None
    street: StreetResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class SparePartCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal | None = None


class SparePartUpdate(BaseModel):
    """Обновление запчасти (все поля необязательны)."""

    name: str | None = None
    description: str | None = None
    price: Decimal | None = None


class SparePartResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseStockCreate(BaseModel):
    """Создание складского остатка.

    Склад и запчасть должны существовать; повторная запись остатка для пары
    (warehouse_id, spare_part_id) запрещена (конфликт) — количество изменяйте
    через обновление существующей записи.
    """

    warehouse_id: int
    spare_part_id: int
    quantity: int = Field(ge=0)


class WarehouseStockUpdate(BaseModel):
    """Изменение количества остатка (обязательное неотрицательное значение)."""

    quantity: int = Field(ge=0)


class WarehouseStockResponse(BaseModel):
    id: int
    warehouse_id: int
    spare_part_id: int
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class WarehouseStockDetailResponse(WarehouseStockResponse):
    """Остаток с раскрытыми связанными складом и запчастью."""

    spare_part: SparePartResponse | None = None
    warehouse: WarehouseResponse | None = None