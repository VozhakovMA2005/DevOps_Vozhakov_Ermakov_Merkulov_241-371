"""Подбор аудитории: правила D1, D2 и D6."""

from __future__ import annotations

import pytest


@pytest.fixture
def fund(client, building, room_types):
    """Небольшой фонд под проверку отбора."""
    payloads = [
        ("101", 1, "LECTURE", "180.00", 70, True),  # лекционная, большая
        ("201", 2, "SEMINAR", "62.50", 24, True),  # семинарская, подходящая
        ("202", 2, "SEMINAR", "30.00", 11, True),  # семинарская, маловата
        ("203", 2, "SEMINAR", "62.50", 24, False),  # семинарская, непригодна
        ("301", 3, "LAB", "108.00", 23, True),  # лаборатория
    ]
    rooms = {}
    for number, floor, type_code, area, seats, usable in payloads:
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": number,
                "floor": floor,
                "room_type_id": room_types[type_code]["id"],
                "area": area,
                "seats": seats,
                "staff_seats": 1,
                "is_usable": usable,
            },
        )
        assert response.status_code == 201, response.json()
        rooms[number] = response.json()
    return rooms


def test_d1_filters_by_matrix(client, fund, discipline):
    """Дисциплина разрешена только в семинарских — лекционная и лаборатория отпадают."""
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}&group_size=20"
    ).json()
    numbers = [item["number"] for item in result["items"]]
    assert numbers == ["201"]
    assert result["rejected"]["D1_not_allowed"] == 2


def test_d6_excludes_unusable(client, fund, discipline):
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}&group_size=5"
    ).json()
    numbers = [item["number"] for item in result["items"]]
    assert "203" not in numbers
    assert result["rejected"]["D6_not_usable"] == 1


def test_d2_filters_by_group_size(client, fund, discipline):
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}&group_size=20"
    ).json()
    assert result["rejected"]["D2_too_small"] == 1  # семинарская на 11 мест


def test_overload_allowed_explicitly(client, fund, discipline):
    """ТЗ D2: перегруз допускается только при явном разрешении и помечается."""
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}"
        "&group_size=20&allow_overload=true"
    ).json()
    numbers = {item["number"]: item for item in result["items"]}
    assert set(numbers) == {"201", "202"}
    assert numbers["202"]["overloaded"] is True
    assert numbers["202"]["seats_margin"] == -9
    assert numbers["201"]["overloaded"] is False


def test_empty_matrix_explains_itself(client, fund, room_types, admin):
    empty = client.post(
        "/api/v1/disciplines",
        json={"code": "NONE", "name": "Без матрицы", "allowed_room_type_ids": []},
    ).json()
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={empty['id']}&group_size=10"
    ).json()
    assert result["items"] == []
    assert "матрица допустимости пуста" in result["reason"]


def test_filter_by_building(client, fund, discipline, building):
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}"
        f"&group_size=5&building_id={building['id']}"
    ).json()
    assert len(result["items"]) >= 1


def test_unknown_discipline(client, fund, admin):
    response = client.get("/api/v1/rooms/suitable?discipline_id=99999&group_size=10")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Границы D2. Добавлено после мутационного прогона: сдвиг условия на единицу
# (margin < -1 вместо margin < 0) проходил незамеченным, потому что прежние
# проверки брали группу намного больше числа мест (пункт 5 задания)
# --------------------------------------------------------------------------- #


def test_d2_group_exactly_fills_the_room(client, fund, discipline):
    """Группа ровно по числу мест проходит: 24 места — группа 24."""
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}&group_size=24"
    ).json()
    numbers = {item["number"] for item in result["items"]}
    assert "201" in numbers
    assert next(i for i in result["items"] if i["number"] == "201")["seats_margin"] == 0


def test_d2_one_person_over_capacity_is_rejected(client, fund, discipline):
    """Граница с другой стороны: группа на одного человека больше — отказ.

    Именно этот случай ловит сдвиг условия на единицу: без него правило
    пропускало бы перегруз на одного человека без явного разрешения.
    """
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}&group_size=25"
    ).json()
    numbers = {item["number"] for item in result["items"]}
    assert "201" not in numbers
    assert result["rejected"]["D2_too_small"] == 2  # и 201 на 24 места, и 202 на 11


def test_d2_one_person_over_capacity_passes_with_overload(client, fund, discipline):
    """Тот же перегруз на одного человека допускается явным разрешением."""
    result = client.get(
        f"/api/v1/rooms/suitable?discipline_id={discipline['id']}"
        "&group_size=25&allow_overload=true"
    ).json()
    room = next(item for item in result["items"] if item["number"] == "201")
    assert room["overloaded"] is True
    assert room["seats_margin"] == -1
