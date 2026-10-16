"""Импорт реестра помещений через HTTP — ТЗ 4.1.1.

Проверяется весь путь: multipart-загрузка, сухой прогон, частичное сохранение,
журнал, отчёт об ошибках и разграничение доступа. Данные берутся из тестовой
базы, которая создаётся заново на каждый прогон (изоляция по пункту 6).
"""

from __future__ import annotations

import dataclasses
import io

import pytest
from openpyxl import Workbook, load_workbook

from app.models import ImportStatus, Role
from app.services.imports import COLUMNS
from tests.conftest import make_user

#: Норма площади у LECTURE — 2.5 м² на человека, поэтому площади здесь
#: заведомо с запасом: иначе строки отклонит правило D5, а проверяем мы не его
GOOD_AREA = 300.0


def book(rows: list[list], *, header: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header if header is not None else list(COLUMNS))
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def upload(client, content: bytes, *, dry_run: bool = False, name: str = "реестр.xlsx"):
    return client.post(
        f"/api/v1/imports/rooms?dry_run={'true' if dry_run else 'false'}",
        files={
            "file": (
                name,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


@pytest.fixture
def registry(building, room_types, department):
    """Корректный файл на две строки и справочники под него."""
    return book(
        [
            ["A", "201", 2, "LECTURE", "KAF-VT", GOOD_AREA, 100, 1, "да", "лекционная"],
            ["A", "202", 2, "SEMINAR", None, 120.0, 25, 1, "нет", None],
        ]
    )


# --------------------------------------------------------------------------- #
# Шаблон-образец
# --------------------------------------------------------------------------- #


def test_template_requires_login(client):
    assert client.get("/api/v1/imports/template.xlsx").status_code == 401


def test_template_is_a_readable_workbook(client, admin):
    response = client.get("/api/v1/imports/template.xlsx")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Помещения", "Как заполнять"]


# --------------------------------------------------------------------------- #
# Сухой прогон
# --------------------------------------------------------------------------- #


def test_dry_run_changes_nothing(client, admin, registry):
    before = client.get("/api/v1/rooms").json()["total"]
    response = upload(client, registry, dry_run=True)

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == ImportStatus.DRY_RUN.value
    assert job["dry_run"] is True
    assert job["rows_total"] == 2
    assert job["rows_created"] == 0
    assert job["rows_updated"] == 0
    assert job["rows_failed"] == 0
    # Главное требование ТЗ к сухому прогону: данные не изменены
    assert client.get("/api/v1/rooms").json()["total"] == before


def test_dry_run_reports_errors_without_saving_good_rows(client, admin, building, room_types):
    content = book(
        [
            ["A", "301", 3, "LECTURE", None, GOOD_AREA, 50, 0, "да", None],
            ["A", "302", 3, "НЕТТАКОГО", None, GOOD_AREA, 50, 0, "да", None],
        ]
    )
    job = upload(client, content, dry_run=True).json()
    assert job["status"] == ImportStatus.DRY_RUN.value
    assert job["rows_failed"] == 1
    assert client.get("/api/v1/rooms?q=301").json()["total"] == 0


# --------------------------------------------------------------------------- #
# Настоящая загрузка
# --------------------------------------------------------------------------- #


def test_import_creates_rooms(client, admin, registry):
    job = upload(client, registry).json()

    assert job["status"] == ImportStatus.APPLIED.value
    assert (job["rows_created"], job["rows_failed"]) == (2, 0)

    rooms = client.get("/api/v1/rooms?q=201").json()["items"]
    assert len(rooms) == 1
    created = rooms[0]
    assert created["floor"] == 2
    assert created["seats"] == 100
    assert created["staff_seats"] == 1
    #: Объём считает база: 100 + 1
    assert created["volume"] == 101


def test_import_writes_initial_measurement(client, admin, registry):
    """Помещение из файла получает запись в истории обмеров с источником IMPORT."""
    upload(client, registry)
    room_id = client.get("/api/v1/rooms?q=201").json()["items"][0]["id"]
    history = client.get(f"/api/v1/rooms/{room_id}/measurements").json()
    assert len(history) == 1
    assert history[0]["source"] == "IMPORT"


def test_repeated_import_updates_and_does_not_duplicate(client, admin, registry):
    upload(client, registry)
    second = upload(client, registry).json()

    assert second["rows_created"] == 0
    assert second["rows_updated"] == 2
    assert client.get("/api/v1/rooms?q=201").json()["total"] == 1


def test_partial_save_keeps_good_rows(client, admin, building, room_types):
    """Ключевое требование ТЗ: ошибка в строке не отменяет остальные строки."""
    content = book(
        [
            ["A", "401", 4, "LECTURE", None, GOOD_AREA, 50, 0, "да", None],
            ["A", "402", 4, "LECTURE", None, "много", 50, 0, "да", None],
            ["A", "403", 0, "LECTURE", None, GOOD_AREA, 50, 0, "да", None],
            ["A", "404", 4, "SEMINAR", None, 120.0, 20, 0, "да", None],
        ]
    )
    job = upload(client, content).json()

    assert job["status"] == ImportStatus.PARTIAL.value
    assert job["rows_total"] == 4
    assert job["rows_created"] == 2
    assert job["rows_failed"] == 2

    codes = {error["error_code"] for error in job["errors"]}
    assert codes == {"NOT_A_NUMBER", "FLOOR_OUT_OF_RANGE"}

    assert client.get("/api/v1/rooms?q=401").json()["total"] == 1
    assert client.get("/api/v1/rooms?q=404").json()["total"] == 1
    assert client.get("/api/v1/rooms?q=402").json()["total"] == 0


def test_all_rows_bad_gives_failed_status(client, admin, building, room_types):
    content = book([["A", "501", 0, "LECTURE", None, GOOD_AREA, 10, 0, "да", None]])
    job = upload(client, content).json()
    assert job["status"] == ImportStatus.FAILED.value
    assert job["rows_created"] == 0


def test_rule_d5_is_applied_to_imported_rows(client, admin, building, room_types):
    """Правила предметной области действуют и на импорт, а не только на форму."""
    content = book([["A", "601", 1, "LECTURE", None, 10.0, 500, 0, "да", None]])
    job = upload(client, content).json()

    assert job["rows_failed"] == 1
    error = job["errors"][0]
    assert error["error_code"] == "D5_NORM_CAPACITY_EXCEEDED"
    assert error["column_name"] == "Мест для обучающихся"


def test_duplicate_inside_file_is_reported_once(client, admin, building, room_types):
    content = book(
        [
            ["A", "701", 1, "LECTURE", None, GOOD_AREA, 10, 0, "да", None],
            ["A", "701", 2, "LECTURE", None, GOOD_AREA, 20, 0, "да", None],
        ]
    )
    job = upload(client, content).json()
    assert job["rows_created"] == 1
    assert job["rows_failed"] == 1
    assert job["errors"][0]["error_code"] == "DUPLICATE_IN_FILE"


def test_blank_tail_rows_are_not_counted(client, admin, building, room_types):
    content = book(
        [
            ["A", "801", 1, "LECTURE", None, GOOD_AREA, 10, 0, "да", None],
            [None] * len(COLUMNS),
            [None] * len(COLUMNS),
        ]
    )
    job = upload(client, content).json()
    assert job["rows_total"] == 1
    assert job["rows_failed"] == 0


# --------------------------------------------------------------------------- #
# Отказ по файлу целиком
# --------------------------------------------------------------------------- #


def test_not_an_xlsx_is_rejected_by_extension(client, admin):
    response = client.post(
        "/api/v1/imports/rooms",
        files={"file": ("реестр.csv", b"A;101", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMPORT_FORMAT_ERROR"


def test_xlsx_name_but_not_xlsx_content_is_rejected(client, admin):
    response = upload(client, b"Korpus;Nomer\nA;101\n")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMPORT_FORMAT_ERROR"


def test_missing_required_column_is_rejected(client, admin):
    without_area = [name for name in COLUMNS if name != "Площадь"]
    response = upload(client, book([["A"] * len(without_area)], header=without_area))
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "IMPORT_FORMAT_ERROR"
    assert "Площадь" in body["error"]["details"]["missing_columns"]


def test_empty_file_is_rejected(client, admin):
    response = upload(client, b"")
    assert response.status_code == 400


def test_file_over_limit_is_rejected(client, admin, app):
    """Предел берётся из настройки MAX_UPLOAD_BYTES, а не зашит в код."""
    app.state.config = dataclasses.replace(app.state.config, max_upload_bytes=1000)
    response = upload(
        client, book([["A", "901", 1, "LECTURE", None, 300, 1, 0, "да", "x" * 400]])
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_failed_format_is_still_written_to_the_log(client, admin):
    """Неудачная попытка остаётся в журнале: иначе её не отследить."""
    before = client.get("/api/v1/imports").json()["total"]
    upload(client, "не книга Excel".encode())
    after = client.get("/api/v1/imports").json()
    assert after["total"] == before + 1
    assert after["items"][0]["status"] == ImportStatus.FAILED.value


# --------------------------------------------------------------------------- #
# Журнал и отчёт
# --------------------------------------------------------------------------- #


def test_log_lists_newest_first(client, admin, registry):
    upload(client, registry, dry_run=True, name="первый.xlsx")
    upload(client, registry, dry_run=True, name="второй.xlsx")
    items = client.get("/api/v1/imports").json()["items"]
    assert items[0]["filename"] == "второй.xlsx"


def test_log_can_be_filtered_by_status(client, admin, registry):
    upload(client, registry, dry_run=True)
    upload(client, registry)
    only_applied = client.get("/api/v1/imports?status=APPLIED").json()["items"]
    assert only_applied and all(
        item["status"] == ImportStatus.APPLIED.value for item in only_applied
    )


def test_job_detail_contains_rows_errors(client, admin, building, room_types):
    content = book([["A", "A01", 0, "LECTURE", None, GOOD_AREA, 10, 0, "да", None]])
    job_id = upload(client, content).json()["id"]
    detail = client.get(f"/api/v1/imports/{job_id}").json()
    assert detail["errors"][0]["row_number"] == 2


def test_unknown_job_gives_404(client, admin):
    response = client.get("/api/v1/imports/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_error_report_is_a_workbook(client, admin, building, room_types):
    content = book([["A", "B01", 0, "LECTURE", None, GOOD_AREA, 10, 0, "да", None]])
    job_id = upload(client, content).json()["id"]

    response = client.get(f"/api/v1/imports/{job_id}/errors.xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Ошибки", "Итог"]
    sheet = workbook["Ошибки"]
    assert sheet.cell(row=1, column=1).value == "Строка файла"
    assert sheet.cell(row=2, column=3).value == "FLOOR_OUT_OF_RANGE"


# --------------------------------------------------------------------------- #
# Доступ по ролям — ТЗ 3.3
# --------------------------------------------------------------------------- #


def test_import_requires_login(client, registry):
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    assert upload(client, registry).status_code == 401


def test_observer_cannot_import(client, session, registry):
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    make_user(session, "observer-imp", Role.OBSERVER)
    client.post(
        "/api/v1/auth/login", json={"username": "observer-imp", "password": "пароль-12345"}
    )
    response = upload(client, registry)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_dispatcher_cannot_import_rooms(client, session, registry):
    """Реестр помещений ведёт администратор фонда, а не диспетчер (ТЗ 3.3)."""
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    make_user(session, "dispatcher-imp", Role.DISPATCHER)
    client.post(
        "/api/v1/auth/login", json={"username": "dispatcher-imp", "password": "пароль-12345"}
    )
    assert upload(client, registry).status_code == 403


def test_observer_can_read_the_log(client, session, admin, registry):
    upload(client, registry, dry_run=True)
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    make_user(session, "observer-log", Role.OBSERVER)
    client.post(
        "/api/v1/auth/login", json={"username": "observer-log", "password": "пароль-12345"}
    )
    assert client.get("/api/v1/imports").status_code == 200
