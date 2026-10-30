"""История обмеров помещения."""

from __future__ import annotations

from datetime import date, timedelta


def test_card_creates_first_measurement(client, room):
    """История начинается с первых значений карточки (источник INITIAL)."""
    history = client.get(f"/api/v1/rooms/{room['id']}/measurements").json()
    assert len(history) == 1
    assert history[0]["source"] == "INITIAL"
    assert history[0]["area"] == "62.50"


def test_new_measurement_updates_the_card(client, room):
    response = client.post(
        f"/api/v1/rooms/{room['id']}/measurements",
        json={
            "area": "70.00",
            "seats": 26,
            "staff_seats": 1,
            "measured_on": "2026-09-15",
            "note": "Обмер после ремонта",
        },
    )
    assert response.status_code == 201
    assert response.json()["measured_by_name"] == "Пользователь admin"

    card = client.get(f"/api/v1/rooms/{room['id']}").json()
    assert card["area"] == "70.00"
    assert card["seats"] == 26
    assert card["volume"] == 27


def test_history_keeps_all_records(client, room):
    """Даты берутся от сегодняшнего дня: первая запись истории заводится
    вместе с карточкой и датируется сегодня, поэтому жёстко прописанные даты
    в прошлом ломали бы порядок сортировки при наступлении этих дат."""
    today = date.today()
    older = (today + timedelta(days=5)).isoformat()
    newer = (today + timedelta(days=15)).isoformat()

    for day, area in ((older, "64.00"), (newer, "66.00")):
        response = client.post(
            f"/api/v1/rooms/{room['id']}/measurements",
            json={"area": area, "seats": 24, "staff_seats": 1, "measured_on": day},
        )
        assert response.status_code == 201, response.json()

    history = client.get(f"/api/v1/rooms/{room['id']}/measurements").json()
    assert len(history) == 3
    # Новые сверху
    assert [row["measured_on"] for row in history] == [newer, older, today.isoformat()]


def test_measurement_obeys_rule_d5(client, room):
    """Обмер — тоже ввод данных, правило проверяется и здесь."""
    response = client.post(
        f"/api/v1/rooms/{room['id']}/measurements",
        json={"area": "30.00", "seats": 24, "staff_seats": 1, "measured_on": "2026-09-15"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "D5_NORM_CAPACITY_EXCEEDED"

    # Карточка не изменилась: отказ не должен оставлять следов
    assert client.get(f"/api/v1/rooms/{room['id']}").json()["area"] == "62.50"


def test_room_with_history_is_not_deleted(client, room):
    response = client.delete(f"/api/v1/rooms/{room['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HAS_DEPENDENTS"


def test_observer_cannot_add_measurement(client, room, session):
    from app.models import Role
    from tests.conftest import make_user

    make_user(session, "observer", Role.OBSERVER)
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login", json={"username": "observer", "password": "пароль-12345"}
    )
    response = client.post(
        f"/api/v1/rooms/{room['id']}/measurements",
        json={"area": "64.00", "seats": 24, "staff_seats": 1, "measured_on": "2026-09-15"},
    )
    assert response.status_code == 403
