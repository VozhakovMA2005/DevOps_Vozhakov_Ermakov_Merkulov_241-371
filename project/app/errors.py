"""Единый формат ответа об ошибке — ТЗ 4.1.6.

Любой отказ уходит клиенту одинаково:

    {"error": {"code": "...", "message": "...", "details": {...}},
     "request_id": "..."}

Тот же идентификатор ставится в заголовок X-Request-Id и пишется в журнал:
пользователь называет его в обращении, и запись находится по одному слову.

Наружу не уходят ни трассировка стека, ни текст SQL, ни значения секретов.
Нарушения правил предметной области несут код правила (D1, D2, D5, D6) —
ТЗ требует, чтобы отказ содержал код правила и причину.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Отказ, который приложение умеет объяснить."""

    status: int = 400
    code: str = "BAD_REQUEST"
    message: str = "Некорректный запрос"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


# --------------------------------------------------------------------------- #
# Формат запроса
# --------------------------------------------------------------------------- #


class InvalidJson(ApiError):
    status, code = 400, "INVALID_JSON"
    message = "Тело запроса не является корректным JSON"


class ValidationFailed(ApiError):
    status, code = 422, "VALIDATION_ERROR"
    message = "Данные не прошли проверку"


class InvalidQueryParam(ApiError):
    status, code = 400, "INVALID_QUERY_PARAM"
    message = "Неверный параметр запроса"


class PayloadTooLarge(ApiError):
    status, code = 413, "FILE_TOO_LARGE"
    message = "Превышен допустимый размер файла"


# --------------------------------------------------------------------------- #
# Доступ
# --------------------------------------------------------------------------- #


class Unauthenticated(ApiError):
    status, code = 401, "UNAUTHENTICATED"
    message = "Требуется вход в систему"


class InvalidCredentials(ApiError):
    status, code = 401, "INVALID_CREDENTIALS"
    message = "Неверный логин или пароль"


class LoginBlocked(ApiError):
    status, code = 401, "LOGIN_TEMPORARILY_BLOCKED"
    message = "Вход временно заблокирован из-за неудачных попыток"


class Forbidden(ApiError):
    status, code = 403, "FORBIDDEN"
    message = "Недостаточно прав для этой операции"


class AccountDisabled(ApiError):
    status, code = 403, "ACCOUNT_DISABLED"
    message = "Учётная запись заблокирована"


# --------------------------------------------------------------------------- #
# Объекты и связи
# --------------------------------------------------------------------------- #


class NotFound(ApiError):
    status, code = 404, "NOT_FOUND"
    message = "Объект не найден"


class RelatedNotFound(ApiError):
    status, code = 409, "RELATED_NOT_FOUND"
    message = "Ссылка на несуществующий объект"


class DuplicateCode(ApiError):
    status, code = 409, "DUPLICATE_CODE"
    message = "Запись с таким кодом уже существует"


class HasDependents(ApiError):
    """ТЗ 4.1.5: удаление записи, на которую ссылаются другие, запрещено."""

    status, code = 409, "HAS_DEPENDENTS"
    message = "На запись ссылаются другие данные, удаление запрещено"


class DepartmentCycle(ApiError):
    status, code = 409, "DEPARTMENT_CYCLE"
    message = "Подразделение не может быть своим предком"


class HistoryImmutable(ApiError):
    """История обмеров не переписывается: исправление — это новый обмер."""

    status, code = 409, "HISTORY_IMMUTABLE"
    message = "Запись истории изменять и удалять нельзя"


class FloorOutOfRange(ApiError):
    status, code = 409, "FLOOR_OUT_OF_RANGE"
    message = "Такого этажа в корпусе нет"


# --------------------------------------------------------------------------- #
# Правила предметной области — ТЗ 4.1.4
# --------------------------------------------------------------------------- #


class RuleD1(ApiError):
    status, code = 409, "D1_DISCIPLINE_NOT_ALLOWED"
    message = "Дисциплина не разрешена в помещении этого типа"


class RuleD2(ApiError):
    status, code = 409, "D2_SEATS_EXCEEDED"
    message = "Численность группы больше числа посадочных мест"


class RuleD5(ApiError):
    status, code = 409, "D5_NORM_CAPACITY_EXCEEDED"
    message = "Посадочных мест больше нормативной вместимости помещения"


class RuleD6(ApiError):
    status, code = 409, "D6_ROOM_NOT_USABLE"
    message = "Помещение непригодно к эксплуатации"


# --------------------------------------------------------------------------- #
# Инфраструктура
# --------------------------------------------------------------------------- #


class DbUnavailable(ApiError):
    status, code = 503, "DB_UNAVAILABLE"
    message = "База данных недоступна"


#: Имя ограничения в БД -> как объяснить отказ человеку
CONSTRAINT_ERRORS: dict[str, tuple[type[ApiError], str]] = {
    "uq_app_user_username": (DuplicateCode, "Пользователь с таким логином уже есть"),
    "uq_department_code": (DuplicateCode, "Подразделение с таким кодом уже есть"),
    "uq_building_code": (DuplicateCode, "Корпус с таким кодом уже есть"),
    "uq_room_type_code": (DuplicateCode, "Тип помещения с таким кодом уже есть"),
    "uq_discipline_code": (DuplicateCode, "Дисциплина с таким кодом уже есть"),
    "uq_room_building_number": (
        DuplicateCode,
        "В этом корпусе уже есть помещение с таким номером",
    ),
    "ck_department_not_self_parent": (
        DepartmentCycle,
        "Подразделение не может быть своим родителем",
    ),
}
