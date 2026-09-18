"""Этаж должен существовать в корпусе."""

from __future__ import annotations

import pytest

from app.errors import FloorOutOfRange
from app.models import Building
from app.services.rooms import check_floor


def building(floors: int, basement: bool) -> Building:
    return Building(
        id=1,
        code="A",
        name="Корпус",
        address="адрес",
        floors_count=floors,
        has_basement=basement,
    )


@pytest.mark.parametrize("floor", [1, 3, 5])
def test_normal_floors(floor):
    check_floor(building(5, False), floor)


def test_basement_allowed_when_building_has_one():
    check_floor(building(5, True), -1)


def test_basement_rejected_without_one():
    with pytest.raises(FloorOutOfRange):
        check_floor(building(5, False), -1)


def test_zero_floor_never_used():
    with pytest.raises(FloorOutOfRange):
        check_floor(building(5, True), 0)


def test_above_top_floor():
    with pytest.raises(FloorOutOfRange) as info:
        check_floor(building(5, False), 6)
    assert info.value.details["allowed"] == "1…5"
