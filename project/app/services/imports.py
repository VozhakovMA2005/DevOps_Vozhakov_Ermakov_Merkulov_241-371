"""Импорт реестра помещений из XLSX — ТЗ 4.1.1.

Четыре требования ТЗ, которые определили устройство этого модуля.

1. «Предварительная валидация загружаемых файлов в режиме сухого прогона
   без изменения данных в БД». Поэтому разбор и запись разделены: сухой
   прогон проходит ровно тот же путь проверок, но помещения не создаёт.

2. «Частичное сохранение корректных строк файла при наличии ошибок в
   отдельных строках». Поэтому каждая строка пишется в своей точке сохранения
   (SAVEPOINT): отказ по одной строке откатывает только её. Без этого первая
   же ошибка уровня базы испортила бы сессию, и пришлось бы отменять весь файл.

3. «Подробное фиксирование причин сбоев в журнале импорта». Поэтому отказ по
   строке превращается не в исключение наружу, а в запись import_row_error с
   кодом, колонкой, значением и текстом по-русски.

4. Правила предметной области проверяются в сервисном слое, а не в
   обработчике. Поэтому импорт зовёт те же check_floor и check_rule_d5, что и
   заведение карточки через веб-форму: один источник истины. Отказ по правилу
   D5 в файле выглядит для пользователя так же, как в форме.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import ApiError, ImportFormatError
from app.models import (
    Building,
    Department,
    ImportJob,
    ImportKind,
    ImportRowError,
    ImportStatus,
    MeasurementSource,
    Room,
    RoomMeasurement,
    RoomType,
)
from app.services.paging import commit
from app.services.rooms import check_floor, check_rule_d5

#: Заголовок колонки в файле -> имя поля. Заголовки по-русски: файл заполняет
#: человек, а ТЗ 4.5 требует русского интерфейса
COLUMNS: dict[str, str] = {
    "Корпус": "building_code",
    "Номер": "number",
    "Этаж": "floor",
    "Тип помещения": "room_type_code",
    "Подразделение": "department_code",
    "Площадь": "area",
    "Мест для обучающихся": "seats",
    "Мест для сотрудников": "staff_seats",
    "Пригодно": "is_usable",
    "Примечание": "note",
}

#: Без этих колонок файл не разобрать вовсе
REQUIRED_COLUMNS: tuple[str, ...] = (
    "Корпус",
    "Номер",
    "Этаж",
    "Тип помещения",
    "Площадь",
)

#: Первая строка — заголовок, данные начинаются со второй. Номера строк в
#: отчёте совпадают с нумерацией Excel, чтобы пользователь нашёл строку глазами
HEADER_ROW = 1
FIRST_DATA_ROW = 2

#: Чтобы «да/нет» из файла не превращались молча в True
TRUE_WORDS = frozenset({"да", "true", "1", "yes", "y", "истина", "+"})
FALSE_WORDS = frozenset({"нет", "false", "0", "no", "n", "ложь", "-"})

TEMPLATE_HINTS: tuple[tuple[str, str], ...] = (
    ("Корпус", "A"),
    ("Номер", "101"),
    ("Этаж", "1"),
    ("Тип помещения", "LECTURE"),
    ("Подразделение", "IT"),
    ("Площадь", "120.50"),
    ("Мест для обучающихся", "100"),
    ("Мест для сотрудников", "1"),
    ("Пригодно", "да"),
    ("Примечание", "необязательное поле"),
)


class RowRejected(Exception):
    """Строка файла отклонена. Наружу не уходит: превращается в запись журнала."""

    def __init__(
        self, code: str, message: str, *, column: str | None = None, value: Any = None
    ) -> None:
        self.code = code
        self.message = message
        self.column = column
        self.value = value
        super().__init__(message)


@dataclass
class RowOutcome:
    """Что получилось со строкой. Нужен, чтобы считать итоги одним местом."""

    created: int = 0
    updated: int = 0
    errors: list[ImportRowError] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Разбор значений
# --------------------------------------------------------------------------- #


def _text(value: Any, column: str, *, required: bool = True, limit: int = 300) -> str | None:
    if value is None:
        if required:
            raise RowRejected("EMPTY", f"Колонка «{column}» не заполнена", column=column)
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise RowRejected("EMPTY", f"Колонка «{column}» не заполнена", column=column)
        return None
    if len(text) > limit:
        raise RowRejected(
            "TOO_LONG",
            f"Значение в колонке «{column}» длиннее {limit} символов",
            column=column,
            value=text[:60],
        )
    return text


def _int(value: Any, column: str, *, default: int | None = None) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is not None:
            return default
        raise RowRejected("EMPTY", f"Колонка «{column}» не заполнена", column=column)
    try:
        # float встречается, потому что Excel хранит числа как числа с точкой
        number = int(float(str(value).replace(",", ".").strip()))
    except (TypeError, ValueError):
        raise RowRejected(
            "NOT_A_NUMBER",
            f"В колонке «{column}» ожидается целое число",
            column=column,
            value=value,
        ) from None
    return number


def _decimal(value: Any, column: str) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RowRejected("EMPTY", f"Колонка «{column}» не заполнена", column=column)
    try:
        number = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, TypeError, ValueError):
        raise RowRejected(
            "NOT_A_NUMBER",
            f"В колонке «{column}» ожидается число",
            column=column,
            value=value,
        ) from None
    if number <= 0:
        raise RowRejected(
            "NOT_POSITIVE",
            f"В колонке «{column}» ожидается число больше нуля",
            column=column,
            value=value,
        )
    return number.quantize(Decimal("0.01"))


def _bool(value: Any, column: str, *, default: bool = True) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise RowRejected(
        "NOT_A_FLAG",
        f"В колонке «{column}» ожидается «да» или «нет»",
        column=column,
        value=value,
    )


# --------------------------------------------------------------------------- #
# Чтение файла
# --------------------------------------------------------------------------- #


def _read_header(sheet: Any) -> dict[str, int]:
    """Заголовок -> номер колонки. Порядок колонок в файле произвольный."""
    header: dict[str, int] = {}
    for index, cell in enumerate(
        next(sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW)), 1
    ):
        title = str(cell.value).strip() if cell.value is not None else ""
        if title in COLUMNS:
            header[title] = index

    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise ImportFormatError(
            "В файле нет обязательных колонок: " + ", ".join(missing),
            details={
                "missing_columns": missing,
                "expected_columns": list(COLUMNS),
                "hint": "Скачайте шаблон-образец и заполните его",
            },
        )
    return header


def _open_sheet(content: bytes) -> tuple[Any, Any]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (
        # openpyxl бросает разное в зависимости от того, чем именно файл не
        # является: не книга Excel, не zip-архив, битый zip, вообще не файл
        InvalidFileException,
        zipfile.BadZipFile,
        KeyError,
        OSError,
        ValueError,
        TypeError,
    ):
        # Пользователю это всё равно одна ошибка
        raise ImportFormatError(
            "Файл не читается как XLSX. Ожидается книга Excel (.xlsx)",
            details={"hint": "Формат .xls и .csv не поддерживается, пересохраните как .xlsx"},
        ) from None
    sheet = workbook.active
    if sheet is None or sheet.max_row is None or sheet.max_row < FIRST_DATA_ROW:
        workbook.close()
        raise ImportFormatError(
            "В файле нет строк с данными: только заголовок или пустой лист",
            details={"hint": "Заполните хотя бы одну строку после заголовка"},
        )
    return workbook, sheet


# --------------------------------------------------------------------------- #
# Одна строка
# --------------------------------------------------------------------------- #


#: Справочники, в которых импорт ищет запись по коду. Ограниченный TypeVar,
#: а не Any: тогда проверка типов видит у каждого варианта поле code и
#: подавлять её не нужно (ТЗ 7.2 запрещает исключения анализаторов без причины)
Coded = TypeVar("Coded", Building, RoomType, Department)


def _resolve(session: Session, model: type[Coded], code: str, column: str) -> Coded:
    obj = session.scalar(select(model).where(model.code == code))
    if obj is None:
        raise RowRejected(
            "UNKNOWN_REFERENCE",
            f"В колонке «{column}» указан код, которого нет в справочнике: {code}",
            column=column,
            value=code,
        )
    return obj


def _parse_row(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    """Значения ячеек -> поля помещения. Любая проблема — RowRejected."""
    building = _resolve(
        session, Building, _text(values.get("Корпус"), "Корпус", limit=20) or "", "Корпус"
    )
    room_type = _resolve(
        session,
        RoomType,
        _text(values.get("Тип помещения"), "Тип помещения", limit=30) or "",
        "Тип помещения",
    )

    department = None
    department_code = _text(
        values.get("Подразделение"), "Подразделение", required=False, limit=30
    )
    if department_code:
        department = _resolve(session, Department, department_code, "Подразделение")

    floor = _int(values.get("Этаж"), "Этаж")
    area = _decimal(values.get("Площадь"), "Площадь")
    seats = _int(values.get("Мест для обучающихся"), "Мест для обучающихся", default=0)
    staff_seats = _int(values.get("Мест для сотрудников"), "Мест для сотрудников", default=0)
    if seats < 0 or staff_seats < 0:
        raise RowRejected(
            "NEGATIVE",
            "Число мест не может быть отрицательным",
            column="Мест для обучающихся",
            value=f"{seats}/{staff_seats}",
        )

    # Те же проверки, что и при заведении карточки вручную. Исключения
    # сервисного слоя несут код правила, его и пишем в журнал
    try:
        check_floor(building, floor)
    except ApiError as error:
        raise RowRejected(error.code, error.message, column="Этаж", value=floor) from error
    try:
        check_rule_d5(room_type, area, seats, staff_seats)
    except ApiError as error:
        # Виновата не площадь, а число мест: площадь — факт обмера, а мест
        # столько, сколько вписали. Поэтому колонка указывается на места
        raise RowRejected(
            error.code,
            error.message,
            column="Мест для обучающихся",
            value=seats + staff_seats,
        ) from error

    return {
        "building_id": building.id,
        "number": _text(values.get("Номер"), "Номер", limit=30),
        "floor": floor,
        "room_type_id": room_type.id,
        "department_id": department.id if department else None,
        "area": area,
        "seats": seats,
        "staff_seats": staff_seats,
        "is_usable": _bool(values.get("Пригодно"), "Пригодно"),
        "note": _text(values.get("Примечание"), "Примечание", required=False, limit=500),
    }


def _apply_row(
    session: Session, fields: dict[str, Any], *, job_id: int, user_id: int | None
) -> str:
    """Создать или обновить помещение. Возвращает «created» или «updated»."""
    existing = session.scalar(
        select(Room).where(
            Room.building_id == fields["building_id"], Room.number == fields["number"]
        )
    )
    if existing is None:
        room = Room(**fields, import_job_id=job_id)
        session.add(room)
        session.flush()
        # История обмеров начинается с первых значений, как и при заведении
        # карточки вручную: иначе в истории появится разрыв
        session.add(
            RoomMeasurement(
                room_id=room.id,
                area=room.area,
                seats=room.seats,
                staff_seats=room.staff_seats,
                measured_on=date.today(),
                measured_by_id=user_id,
                source=MeasurementSource.IMPORT,
                note=f"Импорт, загрузка №{job_id}",
            )
        )
        return "created"

    area_changed = existing.area != fields["area"] or existing.seats != fields["seats"]
    for name, value in fields.items():
        setattr(existing, name, value)
    session.flush()
    if area_changed:
        # Площадь или вместимость изменились — это новый обмер, а не правка
        # прошлого: история не переписывается (ТЗ 4.1.1)
        session.add(
            RoomMeasurement(
                room_id=existing.id,
                area=existing.area,
                seats=existing.seats,
                staff_seats=existing.staff_seats,
                measured_on=date.today(),
                measured_by_id=user_id,
                source=MeasurementSource.IMPORT,
                note=f"Импорт, загрузка №{job_id}",
            )
        )
    return "updated"


# --------------------------------------------------------------------------- #
# Импорт файла
# --------------------------------------------------------------------------- #


def import_rooms(
    session: Session,
    *,
    content: bytes,
    filename: str,
    dry_run: bool,
    user_id: int | None = None,
) -> ImportJob:
    """Разобрать файл и, если это не сухой прогон, внести корректные строки.

    Запись журнала создаётся ДО разбора: если разбор упадёт аварийно, в
    журнале останется запись со статусом PENDING, а не пустота.
    """
    job = ImportJob(
        kind=ImportKind.ROOMS,
        status=ImportStatus.PENDING,
        filename=filename[:255],
        file_size=len(content),
        dry_run=dry_run,
    )
    job.created_by_id = user_id
    session.add(job)
    session.flush()

    try:
        workbook, sheet = _open_sheet(content)
    except ImportFormatError as error:
        job.status = ImportStatus.FAILED
        job.message = error.message
        commit(session)
        raise

    try:
        header = _read_header(sheet)
    except ImportFormatError as error:
        workbook.close()
        job.status = ImportStatus.FAILED
        job.message = error.message
        commit(session)
        raise

    outcome = RowOutcome()
    seen: dict[tuple[Any, str], int] = {}
    rows_total = 0

    for row_number, row in enumerate(
        sheet.iter_rows(min_row=FIRST_DATA_ROW), start=FIRST_DATA_ROW
    ):
        cells = [cell.value for cell in row]
        if all(value is None or str(value).strip() == "" for value in cells):
            continue  # пустая строка в конце файла — не ошибка
        rows_total += 1

        values = {
            title: (cells[index - 1] if index - 1 < len(cells) else None)
            for title, index in header.items()
        }

        try:
            fields = _parse_row(session, values)
        except RowRejected as rejected:
            outcome.errors.append(_row_error(job.id, row_number, rejected))
            continue

        key = (fields["building_id"], str(fields["number"]))
        if key in seen:
            outcome.errors.append(
                _row_error(
                    job.id,
                    row_number,
                    RowRejected(
                        "DUPLICATE_IN_FILE",
                        f"Помещение {fields['number']} уже описано в строке {seen[key]} "
                        "этого же файла",
                        column="Номер",
                        value=fields["number"],
                    ),
                )
            )
            continue
        seen[key] = row_number

        if dry_run:
            # Сухой прогон: проверки прошли, но в базу ничего не пишем
            outcome.created += 1
            continue

        # Своя точка сохранения на строку: отказ уровня базы (например,
        # нарушение CHECK) откатит только эту строку, остальные останутся
        try:
            with session.begin_nested():
                result = _apply_row(session, fields, job_id=job.id, user_id=user_id)
        except SQLAlchemyError as error:
            outcome.errors.append(
                _row_error(
                    job.id,
                    row_number,
                    RowRejected(
                        "DB_REJECTED",
                        _db_reason(error),
                        column="Номер",
                        value=fields["number"],
                    ),
                )
            )
            continue

        if result == "created":
            outcome.created += 1
        else:
            outcome.updated += 1

    workbook.close()

    job.rows_total = rows_total
    job.rows_failed = len(outcome.errors)
    if dry_run:
        job.rows_created = 0
        job.rows_updated = 0
        job.status = ImportStatus.DRY_RUN
        job.message = (
            f"Данные не изменены. При загрузке будет принято строк: "
            f"{outcome.created}, отклонено: {len(outcome.errors)}"
        )
    else:
        job.rows_created = outcome.created
        job.rows_updated = outcome.updated
        if outcome.errors and (outcome.created or outcome.updated):
            job.status = ImportStatus.PARTIAL
        elif outcome.errors:
            job.status = ImportStatus.FAILED
        else:
            job.status = ImportStatus.APPLIED

    for error_row in outcome.errors:
        session.add(error_row)
    commit(session)
    session.refresh(job)
    return job


def _row_error(job_id: int, row_number: int, rejected: RowRejected) -> ImportRowError:
    value = rejected.value
    return ImportRowError(
        job_id=job_id,
        row_number=row_number,
        column_name=rejected.column[:60] if rejected.column else None,
        error_code=rejected.code[:40],
        message=rejected.message[:300],
        value=None if value is None else str(value)[:200],
    )


def _db_reason(error: SQLAlchemyError) -> str:
    """Причина отказа базы для человека. Текст SQL наружу не уходит (ТЗ 4.1.6)."""
    text = str(getattr(error, "orig", error))
    if "uq_room_building_number" in text:
        return "В этом корпусе уже есть помещение с таким номером"
    if "ck_room_floor_not_zero" in text:
        return "Этаж не может быть нулевым"
    if "ck_room_area_positive" in text:
        return "Площадь должна быть больше нуля"
    return "База данных отклонила строку: значения не прошли проверку"


# --------------------------------------------------------------------------- #
# Файлы: шаблон-образец и отчёт об ошибках
# --------------------------------------------------------------------------- #


def build_template() -> bytes:
    """Шаблон-образец для загрузки (ТЗ 4.1.1: «предоставление шаблонов-образцов»)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Помещения"
    sheet.append(list(COLUMNS))
    sheet.append([value for _, value in TEMPLATE_HINTS])

    notes = workbook.create_sheet("Как заполнять")
    notes.append(["Колонка", "Обязательна", "Что писать"])
    rules = {
        "Корпус": "код корпуса из справочника, например A",
        "Номер": "номер помещения в корпусе, уникален внутри корпуса",
        "Этаж": "целое число, 0 недопустим, подвал — отрицательное",
        "Тип помещения": "код типа из справочника, например LECTURE",
        "Подразделение": "код подразделения или пусто",
        "Площадь": "рабочая площадь в м², больше нуля",
        "Мест для обучающихся": "целое число, по умолчанию 0",
        "Мест для сотрудников": "целое число, по умолчанию 0",
        "Пригодно": "да или нет, по умолчанию да",
        "Примечание": "свободный текст или пусто",
    }
    for title in COLUMNS:
        notes.append([title, "да" if title in REQUIRED_COLUMNS else "нет", rules[title]])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def build_error_report(job: ImportJob) -> bytes:
    """Отчёт об ошибках импорта в XLSX (ТЗ 4.1.1)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ошибки"
    sheet.append(["Строка файла", "Колонка", "Код", "Причина", "Значение"])
    for error in job.errors:
        sheet.append(
            [
                error.row_number,
                error.column_name or "",
                error.error_code,
                error.message,
                error.value or "",
            ]
        )

    summary = workbook.create_sheet("Итог")
    summary.append(["Загрузка", job.id])
    summary.append(["Файл", job.filename])
    summary.append(["Сухой прогон", "да" if job.dry_run else "нет"])
    summary.append(["Статус", job.status.value])
    summary.append(["Строк всего", job.rows_total])
    summary.append(["Создано", job.rows_created])
    summary.append(["Обновлено", job.rows_updated])
    summary.append(["Отклонено", job.rows_failed])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def query_jobs(kind: ImportKind | None = None, status: ImportStatus | None = None) -> Any:
    statement = select(ImportJob).order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
    if kind is not None:
        statement = statement.where(ImportJob.kind == kind)
    if status is not None:
        statement = statement.where(ImportJob.status == status)
    return statement
