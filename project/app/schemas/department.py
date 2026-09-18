"""Схемы подразделения."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import OrmSchema, Schema


class DepartmentCreate(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    head_fio: str | None = Field(default=None, max_length=150)


class DepartmentUpdate(Schema):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = None
    head_fio: str | None = Field(default=None, max_length=150)


class DepartmentOut(OrmSchema):
    id: int
    code: str
    name: str
    parent_id: int | None
    head_fio: str | None
