"""Схемы типа помещения."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, field_serializer

from app.schemas.common import OrmSchema, Schema


class RoomTypeCreate(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    area_norm: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    is_teaching: bool = True
    note: str | None = Field(default=None, max_length=300)


class RoomTypeUpdate(Schema):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    area_norm: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    is_teaching: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class RoomTypeOut(OrmSchema):
    id: int
    code: str
    name: str
    area_norm: Decimal | None
    is_teaching: bool
    note: str | None

    @field_serializer("area_norm")
    def _norm(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.2f}"

    def normative_capacity_for(self, area: Decimal) -> int | None:
        """Правило D5: сколько человек допускает норма при такой площади."""
        if self.area_norm is None or self.area_norm <= 0:
            return None
        return int(area // self.area_norm)
