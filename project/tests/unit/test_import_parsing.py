"""Разбор значений из XLSX: ошибочные данные и граничные случаи.

Базы для этих проверок не нужно — разбор ячейки от неё не зависит. Проверяется
именно то, чего ждёт пункт 5 задания: ошибочные данные, границы и обязательные
правила. Каждый случай — отдельная проверка, чтобы по упавшему имени сразу было
видно, какой именно ввод перестал обрабатываться.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.errors import ImportFormatError
from app.services.imports import (
    COLUMNS,
    REQUIRED_COLUMNS,
    RowRejected,
    _bool,
    _decimal,
    _int,
    _open_sheet,
    _read_header,
    _text,
    build_template,
)


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


# --------------------------------------------------------------------------- #
# Текст
# --------------------------------------------------------------------------- #


def test_text_strips_spaces():
    assert _text("  101  ", "Номер") == "101"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_text_requires_value(value):
    with pytest.raises(RowRejected) as info:
        _text(value, "Номер")
    assert info.value.code == "EMPTY"
    assert info.value.column == "Номер"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_text_allows_empty_when_optional(value):
    assert _text(value, "Примечание", required=False) is None


def test_text_rejects_too_long():
    with pytest.raises(RowRejected) as info:
        _text("я" * 31, "Номер", limit=30)
    assert info.value.code == "TOO_LONG"


def test_text_accepts_value_exactly_at_limit():
    """Граница: ровно предел — ещё можно."""
    assert _text("я" * 30, "Номер", limit=30) == "я" * 30


# --------------------------------------------------------------------------- #
# Целые
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3), ("3", 3), (3.0, 3), ("3.0", 3), (" 3 ", 3), ("-1", -1), ("3,0", 3)],
)
def test_int_accepts_excel_variants(value, expected):
    """Excel отдаёт числа то целыми, то с точкой, то с запятой."""
    assert _int(value, "Этаж") == expected


@pytest.mark.parametrize("value", ["много", "1 этаж", "", None, "--3"])
def test_int_rejects_non_numbers(value):
    with pytest.raises(RowRejected):
        _int(value, "Этаж")


def test_int_uses_default_for_empty():
    assert _int(None, "Мест для сотрудников", default=0) == 0
    assert _int("", "Мест для сотрудников", default=0) == 0


# --------------------------------------------------------------------------- #
# Числа с дробной частью
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [("120.5", "120.50"), ("120,5", "120.50"), (120.5, "120.50"), ("0.01", "0.01")],
)
def test_decimal_accepts_both_separators(value, expected):
    assert _decimal(value, "Площадь") == Decimal(expected)


@pytest.mark.parametrize("value", ["0", "-1", "0.00", "-0.01"])
def test_decimal_rejects_non_positive(value):
    """Площадь строго больше нуля: это ограничение и в схеме базы."""
    with pytest.raises(RowRejected) as info:
        _decimal(value, "Площадь")
    assert info.value.code == "NOT_POSITIVE"


@pytest.mark.parametrize("value", ["", None, "примерно сто"])
def test_decimal_rejects_garbage(value):
    with pytest.raises(RowRejected):
        _decimal(value, "Площадь")


def test_decimal_rounds_to_two_places():
    """В базе Numeric(9, 2): третий знак надо отбросить здесь, а не в базе."""
    assert _decimal("120.567", "Площадь") == Decimal("120.57")


# --------------------------------------------------------------------------- #
# Признаки «да/нет»
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["да", "ДА", "true", "1", "+", "yes", True])
def test_bool_true_words(value):
    assert _bool(value, "Пригодно") is True


@pytest.mark.parametrize("value", ["нет", "НЕТ", "false", "0", "-", "no", False])
def test_bool_false_words(value):
    assert _bool(value, "Пригодно") is False


def test_bool_empty_takes_default():
    assert _bool(None, "Пригодно") is True
    assert _bool("", "Пригодно", default=False) is False


@pytest.mark.parametrize("value", ["возможно", "2", "ага"])
def test_bool_rejects_unknown_words(value):
    """Непонятное слово не должно молча превращаться в «да»."""
    with pytest.raises(RowRejected) as info:
        _bool(value, "Пригодно")
    assert info.value.code == "NOT_A_FLAG"


# --------------------------------------------------------------------------- #
# Файл целиком
# --------------------------------------------------------------------------- #


def test_header_allows_any_column_order():
    reversed_header = list(reversed(list(COLUMNS)))
    workbook, sheet = _open_sheet(book([["A"] * len(COLUMNS)], header=reversed_header))
    header = _read_header(sheet)
    workbook.close()
    assert set(header) == set(COLUMNS)


def test_header_without_required_column_is_rejected():
    without_area = [name for name in COLUMNS if name != "Площадь"]
    workbook, sheet = _open_sheet(book([["x"] * len(without_area)], header=without_area))
    with pytest.raises(ImportFormatError) as info:
        _read_header(sheet)
    workbook.close()
    assert "Площадь" in info.value.details["missing_columns"]


def test_header_ignores_unknown_columns():
    """Лишняя колонка — не ошибка: в реестре университета их бывает много."""
    header = [*COLUMNS, "Инвентарный номер"]
    workbook, sheet = _open_sheet(book([["x"] * len(header)], header=header))
    assert "Инвентарный номер" not in _read_header(sheet)
    workbook.close()


def test_not_an_xlsx_is_rejected():
    with pytest.raises(ImportFormatError):
        _open_sheet(b"Korpus;Nomer\nA;101\n")


def test_file_with_only_header_is_rejected():
    with pytest.raises(ImportFormatError) as info:
        _open_sheet(book([]))
    assert "нет строк с данными" in info.value.message


def test_empty_bytes_are_rejected():
    with pytest.raises(ImportFormatError):
        _open_sheet(b"")


# --------------------------------------------------------------------------- #
# Шаблон-образец
# --------------------------------------------------------------------------- #


def test_template_matches_expected_columns():
    """Шаблон обязан подходить под свой же разбор, иначе он бесполезен."""
    workbook, sheet = _open_sheet(build_template())
    header = _read_header(sheet)
    workbook.close()
    assert set(header) == set(COLUMNS)
    assert set(REQUIRED_COLUMNS) <= set(header)
