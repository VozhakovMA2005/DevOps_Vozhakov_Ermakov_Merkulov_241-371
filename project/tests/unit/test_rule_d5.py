"""Правило D5 в чистом виде: расчёт нормативной вместимости.

D5: нормативная вместимость = рабочая площадь / норма площади на человека,
округление вниз. Суммарное число мест не должно её превышать.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.errors import RuleD5
from app.models import RoomType
from app.services.rooms import check_rule_d5


def room_type(norm: str | None) -> RoomType:
    return RoomType(code="T", name="Тип", area_norm=None if norm is None else Decimal(norm))


@pytest.mark.parametrize(
    ("area", "norm", "expected"),
    [
        ("62.50", "2.50", 25),  # ровно делится
        ("62.49", "2.50", 24),  # округление вниз, а не по правилам математики
        ("100.00", "6.00", 16),  # 16.66 -> 16
        ("2.49", "2.50", 0),  # меньше нормы на одного человека
    ],
)
def test_normative_capacity(area, norm, expected):
    assert room_type(norm).normative_capacity(Decimal(area)) == expected


def test_norm_not_set_means_no_limit():
    """Служебным помещениям норма не задана — правило не применяется."""
    assert room_type(None).normative_capacity(Decimal("10.00")) is None
    check_rule_d5(room_type(None), Decimal("10.00"), 1000, 1000)


def test_exactly_at_norm_is_allowed():
    check_rule_d5(room_type("2.50"), Decimal("62.50"), 24, 1)


def test_one_over_norm_is_rejected():
    with pytest.raises(RuleD5) as info:
        check_rule_d5(room_type("2.50"), Decimal("62.50"), 24, 2)
    details = info.value.details
    assert details["rule"] == "D5"
    assert details["normative_capacity"] == 25
    assert details["requested_total_seats"] == 26
    assert details["excess"] == 1


def test_staff_seats_count_towards_the_limit():
    """Места сотрудников входят в D5 наравне с местами обучающихся."""
    check_rule_d5(room_type("2.50"), Decimal("25.00"), 10, 0)
    with pytest.raises(RuleD5):
        check_rule_d5(room_type("2.50"), Decimal("25.00"), 10, 1)


# --------------------------------------------------------------------------- #
# Округление. Эти проверки добавлены после мутационного прогона: подмена
# округления вниз на округление вверх проходила незамеченной, потому что все
# прежние площади делились на норму без остатка (пункт 5 задания)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("area", "norm", "expected"),
    [
        ("63.00", "2.50", 25),  # 25.2 — вниз 25, вверх было бы 26
        ("62.50", "2.50", 25),  # делится ровно: вниз и вверх совпадают
        ("64.90", "2.50", 25),  # 25.96 — почти 26, но всё ещё 25
        ("65.00", "2.50", 26),  # ровно 26
        ("2.49", "2.50", 0),  # меньше нормы на одного человека — ни одного места
        ("7.50", "2.00", 3),  # 3.75 — вниз 3
    ],
)
def test_normative_capacity_rounds_down(area, norm, expected):
    """D5 округляет вниз: человека нельзя посадить на дробную часть площади."""
    room_type = RoomType(code="X", name="Тип", area_norm=Decimal(norm))
    assert room_type.normative_capacity(Decimal(area)) == expected


def test_remainder_does_not_add_a_seat():
    """Прямая формулировка правила: остаток площади места не добавляет."""
    room_type = RoomType(code="X", name="Тип", area_norm=Decimal("2.50"))
    exact = room_type.normative_capacity(Decimal("62.50"))
    with_remainder = room_type.normative_capacity(Decimal("64.99"))
    assert exact == with_remainder == 25
