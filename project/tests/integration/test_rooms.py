"""Помещения, объём и правило D5 на живой базе."""

from __future__ import annotations

import pytest


class TestRoomCard:
    def test_volume_is_computed_by_database(self, client, room):
        """ТЗ 4.1.1: суммарный объём считает база, приложение его не пишет."""
        assert room["volume"] == room["seats"] + room["staff_seats"] == 25

    def test_volume_cannot_be_sent(self, client, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "999",
                "floor": 1,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "50.00",
                "seats": 10,
                "staff_seats": 1,
                "volume": 500,
            },
        )
        assert response.status_code == 422

    def test_volume_follows_seats(self, client, room):
        updated = client.patch(f"/api/v1/rooms/{room['id']}", json={"seats": 20}).json()
        assert updated["volume"] == 21

    def test_area_is_a_string_with_two_digits(self, client, room):
        assert room["area"] == "62.50"

    def test_normative_capacity_is_shown(self, client, room):
        assert room["normative_capacity"] == 25

    def test_duplicate_number_in_same_building(self, client, room, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "201",
                "floor": 3,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "40.00",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DUPLICATE_CODE"

    def test_same_number_in_another_building_is_fine(self, client, room, room_types, admin):
        other = client.post(
            "/api/v1/buildings",
            json={"code": "B", "name": "Второй", "address": "адрес", "floors_count": 3},
        ).json()
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": other["id"],
                "number": "201",
                "floor": 2,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "40.00",
                "seats": 15,
            },
        )
        assert response.status_code == 201


class TestRuleD5:
    """Ключевое правило предметной области этапа 1."""

    def test_seats_within_norm_allowed(self, client, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "301",
                "floor": 3,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "62.50",
                "seats": 24,
                "staff_seats": 1,
            },
        )
        assert response.status_code == 201

    def test_seats_above_norm_rejected(self, client, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "302",
                "floor": 3,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "62.50",
                "seats": 30,
                "staff_seats": 1,
            },
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "D5_NORM_CAPACITY_EXCEEDED"
        assert error["details"]["rule"] == "D5"
        assert error["details"]["normative_capacity"] == 25
        assert error["details"]["excess"] == 6

    def test_rule_applies_on_update(self, client, room):
        response = client.patch(f"/api/v1/rooms/{room['id']}", json={"seats": 40})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "D5_NORM_CAPACITY_EXCEEDED"

    def test_shrinking_area_can_break_the_rule(self, client, room):
        """Уменьшение площади при тех же местах — то же нарушение D5."""
        response = client.patch(f"/api/v1/rooms/{room['id']}", json={"area": "30.00"})
        assert response.status_code == 409
        assert response.json()["error"]["details"]["normative_capacity"] == 12

    def test_type_without_norm_has_no_limit(self, client, building, room_types):
        """Служебному помещению норма не задана — правило не применяется."""
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "401",
                "floor": 4,
                "room_type_id": room_types["OFFICE"]["id"],
                "area": "12.00",
                "seats": 0,
                "staff_seats": 50,
            },
        )
        assert response.status_code == 201
        assert response.json()["normative_capacity"] is None

    def test_changing_type_rechecks_the_rule(self, client, room, room_types):
        """Компьютерный класс требует 6 м² на место: 24 места в 62.50 м² не влезут."""
        response = client.patch(
            f"/api/v1/rooms/{room['id']}", json={"room_type_id": room_types["COMPUTER"]["id"]}
        )
        assert response.status_code == 409
        assert response.json()["error"]["details"]["normative_capacity"] == 10


class TestFloors:
    def test_floor_must_exist_in_building(self, client, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "901",
                "floor": 9,
                "room_type_id": room_types["SEMINAR"]["id"],
                "area": "40.00",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "FLOOR_OUT_OF_RANGE"
        assert response.json()["error"]["details"]["allowed"] == "−1 (подвал), 1…5"

    def test_basement_allowed(self, client, building, room_types):
        response = client.post(
            "/api/v1/rooms",
            json={
                "building_id": building["id"],
                "number": "-101",
                "floor": -1,
                "room_type_id": room_types["UTILITY"]["id"],
                "area": "40.00",
            },
        )
        assert response.status_code == 201


class TestFilters:
    @pytest.fixture
    def rooms(self, client, building, room_types):
        payloads = [
            ("101", 1, "LECTURE", "180.00", 70, True),
            ("102", 1, "LECTURE", "150.00", 58, True),
            ("201", 2, "SEMINAR", "62.50", 24, True),
            ("202", 2, "COMPUTER", "96.00", 15, False),
        ]
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
        return payloads

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("", 4),
            ("floor=1", 2),
            ("floor=2", 2),
            ("is_usable=false", 1),
            ("is_usable=true", 3),
            ("area_min=100", 2),
            ("area_max=100", 2),
            ("area_min=60&area_max=100", 2),
            ("q=10", 2),
        ],
    )
    def test_filters(self, client, rooms, query, expected):
        assert client.get(f"/api/v1/rooms?{query}").json()["total"] == expected

    def test_pagination(self, client, rooms):
        page = client.get("/api/v1/rooms?page=2&page_size=3").json()
        assert page["total"] == 4
        assert page["pages"] == 2
        assert len(page["items"]) == 1

    def test_filter_by_type(self, client, rooms, room_types):
        page = client.get(f"/api/v1/rooms?room_type_id={room_types['LECTURE']['id']}").json()
        assert page["total"] == 2


class TestDependents:
    """Что помещения запрещают удалять в справочниках."""

    def test_building_with_rooms_is_not_deleted(self, client, room, building):
        response = client.delete(f"/api/v1/buildings/{building['id']}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "HAS_DEPENDENTS"
        assert response.json()["error"]["details"]["rooms_count"] == 1

    def test_floors_navigation(self, client, room, building):
        body = client.get(f"/api/v1/buildings/{building['id']}/floors").json()
        assert body["floors"] == [{"floor": 2, "rooms_count": 1}]

    def test_department_with_rooms_is_not_deleted(self, client, room, department, building):
        client.patch(f"/api/v1/rooms/{room['id']}", json={"department_id": department["id"]})
        response = client.delete(f"/api/v1/departments/{department['id']}")
        assert response.status_code == 409
        assert response.json()["error"]["details"]["rooms_count"] == 1

    def test_type_in_use_is_not_deleted(self, client, room, room_types):
        response = client.delete(f"/api/v1/room-types/{room_types['SEMINAR']['id']}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "HAS_DEPENDENTS"


def test_section_requires_login(client):
    assert client.get("/api/v1/rooms").status_code == 401
