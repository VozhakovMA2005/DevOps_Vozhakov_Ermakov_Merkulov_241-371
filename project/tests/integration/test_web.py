"""Веб-интерфейс: страницы отдаются, вход обязателен, оформление локальное."""

from __future__ import annotations

import pytest

PAGES = ["/", "/disciplines", "/selection"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_require_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_for_logged_in_user(client, admin, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_login_page_is_open(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Пароль" in response.text


def test_no_external_cdn(client, admin):
    """ТЗ 4.5: оформление хранится локально, внешние CDN запрещены."""
    for path in ["/login", "/"]:
        text = client.get(path).text
        assert "cdn.jsdelivr" not in text
        assert "cdnjs" not in text
        assert "unpkg" not in text
        assert "/static/vendor/bootstrap/bootstrap.min.css" in text


def test_bootstrap_is_served_locally(client):
    response = client.get("/static/vendor/bootstrap/bootstrap.min.css")
    assert response.status_code == 200
    assert len(response.content) > 100_000


def test_breadcrumbs_on_room_card(client, room, building):
    text = client.get(f"/rooms/{room['id']}").text
    assert "breadcrumb" in text
    assert f"/buildings/{building['id']}" in text
    assert "Помещение 201" in text


def test_room_card_shows_history_and_norm(client, room):
    text = client.get(f"/rooms/{room['id']}").text
    assert "История обмеров" in text
    assert "Норматив D5" in text


def test_floor_page_lists_rooms(client, room, building):
    text = client.get(f"/buildings/{building['id']}/floors/2").text
    assert "201" in text
    assert "Объём" in text


def test_observer_sees_no_edit_buttons(client, session, building):
    from app.models import Role
    from tests.conftest import make_user

    make_user(session, "observer", Role.OBSERVER)
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login", json={"username": "observer", "password": "пароль-12345"}
    )
    text = client.get("/").text
    assert "Добавить корпус" not in text


def test_writer_sees_edit_buttons(client, building):
    assert "Добавить корпус" in client.get("/").text


def test_imports_page_requires_login(client):
    response = client.get("/imports", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_imports_page_shows_the_log(client, admin, building, room_types):
    """Страница импорта отдаётся и показывает журнал загрузок."""
    import io

    from openpyxl import Workbook

    from app.services.imports import COLUMNS

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(COLUMNS))
    sheet.append(["A", "W01", 1, "LECTURE", None, 300.0, 50, 0, "да", None])
    buffer = io.BytesIO()
    workbook.save(buffer)
    client.post(
        "/api/v1/imports/rooms?dry_run=true",
        files={"file": ("страница.xlsx", buffer.getvalue(), "application/octet-stream")},
    )

    response = client.get("/imports")
    assert response.status_code == 200
    assert "Импорт реестра помещений" in response.text
    assert "страница.xlsx" in response.text
    assert "Скачать шаблон-образец" in response.text
