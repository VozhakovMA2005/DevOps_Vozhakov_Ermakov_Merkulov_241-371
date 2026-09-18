"""Схемы дисциплины и матрицы допустимости (правило D1)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import OrmSchema, Schema
from app.schemas.room_type import RoomTypeOut


class DisciplineCreate(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=300)
    #: Типы помещений, разрешённые этой дисциплине — матрица допустимости (D1)
    allowed_room_type_ids: list[int] = Field(default_factory=list)


class DisciplineUpdate(Schema):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=300)
    allowed_room_type_ids: list[int] | None = None


class DisciplineOut(OrmSchema):
    id: int
    code: str
    name: str
    note: str | None
    allowed_room_types: list[RoomTypeOut]
