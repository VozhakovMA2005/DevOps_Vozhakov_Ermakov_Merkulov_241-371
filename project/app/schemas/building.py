"""Схемы корпуса."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, field_serializer

from app.schemas.common import OrmSchema, Schema


class BuildingCreate(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=300)
    floors_count: int = Field(ge=1, le=100)
    has_basement: bool = False
    passport_area: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class BuildingUpdate(Schema):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    floors_count: int | None = Field(default=None, ge=1, le=100)
    has_basement: bool | None = None
    passport_area: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class BuildingOut(OrmSchema):
    id: int
    code: str
    name: str
    address: str
    floors_count: int
    has_basement: bool
    passport_area: Decimal | None

    @field_serializer("passport_area")
    def _area(self, value: Decimal | None) -> str | None:
        # ТЗ 4.1.3: площади уходят строкой с двумя знаками, а не float
        return None if value is None else f"{value:.2f}"
