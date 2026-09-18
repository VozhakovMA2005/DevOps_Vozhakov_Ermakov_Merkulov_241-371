"""Мелочи, нужные всем сервисам: поиск объекта, разбор ограничений БД, страницы."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import (
    CONSTRAINT_ERRORS,
    ApiError,
    DuplicateCode,
    InvalidQueryParam,
    NotFound,
    RelatedNotFound,
)

Model = TypeVar("Model")

ENTITY_LABELS = {
    "AppUser": "Пользователь",
    "Building": "Корпус",
    "Department": "Подразделение",
    "Discipline": "Дисциплина",
    "Room": "Помещение",
    "RoomMeasurement": "Обмер",
    "RoomType": "Тип помещения",
}


def label_of(model: type) -> str:
    return ENTITY_LABELS.get(model.__name__, model.__name__)


def get_or_404(session: Session, model: type[Model], obj_id: int) -> Model:
    obj = session.get(model, obj_id)
    if obj is None:
        raise NotFound(f"{label_of(model)} с идентификатором {obj_id} не найден")
    return obj


def get_related_or_409(session: Session, model: type[Model], obj_id: int, field: str) -> Model:
    """Ссылка на несуществующий объект — это не «страница не найдена»."""
    obj = session.get(model, obj_id)
    if obj is None:
        raise RelatedNotFound(
            f"{label_of(model)} с идентификатором {obj_id} не найден",
            details={"field": field, "value": obj_id},
        )
    return obj


def translate_integrity_error(error: IntegrityError) -> ApiError:
    """Ограничение БД -> понятный отказ. Текст SQL наружу не уходит (ТЗ 4.1.6)."""
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint and constraint in CONSTRAINT_ERRORS:
        cls, message = CONSTRAINT_ERRORS[constraint]
        return cls(message, details={"constraint": constraint})
    return DuplicateCode(
        "Запись нарушает ограничение целостности данных",
        details={"constraint": constraint} if constraint else {},
    )


def changed_fields(payload: Any) -> dict[str, Any]:
    """Только то, что клиент прислал явно: PATCH не должен затирать остальное."""
    return payload.model_dump(exclude_unset=True)


def parse_int_param(name: str, raw: str | None, *, minimum: int | None = None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise InvalidQueryParam(
            f"Параметр {name} должен быть целым числом, получено: {raw!r}",
            details={"param": name, "value": raw},
        ) from None
    if minimum is not None and value < minimum:
        raise InvalidQueryParam(
            f"Параметр {name} должен быть не меньше {minimum}",
            details={"param": name, "value": value},
        )
    return value


def parse_bool_param(name: str, raw: str | None) -> bool | None:
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "да", "yes"):
        return True
    if lowered in ("false", "0", "нет", "no"):
        return False
    raise InvalidQueryParam(
        f"Параметр {name} должен быть true или false, получено: {raw!r}",
        details={"param": name, "value": raw},
    )
