"""Схемы помещения.

Объём (вместимость) во входных данных не принимается: его считает база —
правило из ТЗ 4.1.1. Поле normative_capacity — тоже расчётное, отдаётся только
на выход, чтобы человек видел, сколько мест допускает норма (правило D5).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, computed_field, field_serializer

from app.schemas.common import OrmSchema, Schema
from app.schemas.room_type import RoomTypeOut


class RoomCreate(Schema):
    building_id: int
    number: str = Field(min_length=1, max_length=30)
    floor: int = Field(ge=-1, le=100)
    room_type_id: int
    department_id: int | None = None
    area: Decimal = Field(gt=0, max_digits=9, decimal_places=2)
    seats: int = Field(default=0, ge=0, le=10000)
    staff_seats: int = Field(default=0, ge=0, le=1000)
    is_usable: bool = True
    note: str | None = Field(default=None, max_length=500)


class RoomUpdate(Schema):
    number: str | None = Field(default=None, min_length=1, max_length=30)
    floor: int | None = Field(default=None, ge=-1, le=100)
    room_type_id: int | None = None
    department_id: int | None = None
    area: Decimal | None = Field(default=None, gt=0, max_digits=9, decimal_places=2)
    seats: int | None = Field(default=None, ge=0, le=10000)
    staff_seats: int | None = Field(default=None, ge=0, le=1000)
    is_usable: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class RoomOut(OrmSchema):
    id: int
    building_id: int
    number: str
    floor: int
    room_type_id: int
    department_id: int | None
    area: Decimal
    seats: int
    staff_seats: int
    #: Считает база: seats + staff_seats
    volume: int
    is_usable: bool
    note: str | None
    room_type: RoomTypeOut

    @field_serializer("area")
    def _area(self, value: Decimal) -> str:
        return f"{value:.2f}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def normative_capacity(self) -> int | None:
        """Правило D5: площадь / норма на человека, округление вниз."""
        return self.room_type.normative_capacity_for(self.area)
