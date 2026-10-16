"""Схемы журнала импорта.

Входной схемы здесь нет: на вход приходит файл (multipart/form-data), а не
JSON. Поэтому проверка входа — это проверка самого файла в сервисном слое.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import computed_field

from app.models import ImportKind, ImportStatus
from app.schemas.common import OrmSchema

#: Статус -> как объяснить его человеку (ТЗ 4.5: интерфейс по-русски)
STATUS_TITLES: dict[ImportStatus, str] = {
    ImportStatus.PENDING: "разбор не завершён",
    ImportStatus.DRY_RUN: "сухой прогон, данные не изменены",
    ImportStatus.APPLIED: "все строки приняты",
    ImportStatus.PARTIAL: "часть строк принята, часть отклонена",
    ImportStatus.FAILED: "не принято ни одной строки",
}

KIND_TITLES: dict[ImportKind, str] = {
    ImportKind.ROOMS: "реестр помещений",
    ImportKind.STUDENTS: "списки обучающихся",
}


class ImportRowErrorOut(OrmSchema):
    row_number: int
    column_name: str | None
    error_code: str
    message: str
    value: str | None


class ImportJobOut(OrmSchema):
    id: int
    kind: ImportKind
    status: ImportStatus
    filename: str
    file_size: int
    dry_run: bool
    rows_total: int
    rows_created: int
    rows_updated: int
    rows_failed: int
    message: str | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]  # property, а mypy ждёт метод
    @property
    def status_title(self) -> str:
        return STATUS_TITLES[self.status]

    @computed_field  # type: ignore[prop-decorator]  # property, а mypy ждёт метод
    @property
    def kind_title(self) -> str:
        return KIND_TITLES[self.kind]


class ImportJobDetail(ImportJobOut):
    """Журнал с построчными ошибками — то, что показывают пользователю после
    загрузки и что выгружается отчётом."""

    errors: list[ImportRowErrorOut]
