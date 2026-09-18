"""Схемы обмера помещения."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field, field_serializer

from app.models.measurement import MeasurementSource
from app.schemas.common import OrmSchema, Schema


class MeasurementCreate(Schema):
    area: Decimal = Field(gt=0, max_digits=9, decimal_places=2)
    seats: int = Field(ge=0, le=10000)
    staff_seats: int = Field(ge=0, le=1000)
    measured_on: date
    note: str | None = Field(default=None, max_length=300)


class MeasurementOut(OrmSchema):
    id: int
    room_id: int
    area: Decimal
    seats: int
    staff_seats: int
    measured_on: date
    source: MeasurementSource
    note: str | None
    measured_by_name: str | None = None

    @field_serializer("area")
    def _area(self, value: Decimal) -> str:
        return f"{value:.2f}"
