"""Общие части схем: постраничный вывод и запрет полей только для чтения."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

#: Поля, которые считает приложение или база. Клиент их прислать не может
READ_ONLY_FIELDS = frozenset(
    {
        "id",
        "volume",
        "created_at",
        "updated_at",
        "password_hash",
        "normative_capacity",
        "failed_attempts",
        "locked_until",
        "last_login_at",
    }
)


class Schema(BaseModel):
    """Вход. Лишние поля — ошибка, а не молчаливое игнорирование."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrmSchema(BaseModel):
    """Выход. Собирается прямо из объекта модели."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def page_envelope(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }
