"""Корпуса: операции, ограничения, формат ответа об ошибке."""

from __future__ import annotations

import pytest

from app.models import Role
from tests.conftest import make_user


class TestBuildings:
    def test_lifecycle(self, client, admin):
        created = client.post(
            "/api/v1/buildings",
            json={
                "code": "A",
                "name": "Главный",
                "address": "ул. Чехова, 2",
                "floors_count": 5,
                "has_basement": True,
                "passport_area": "9800.00",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["passport_area"] == "9800.00"  # строка, не float (ТЗ 4.1.3)

        patched = client.patch(f"/api/v1/buildings/{body['id']}", json={"floors_count": 7})
        assert patched.json()["floors_count"] == 7
        assert patched.json()["name"] == "Главный"  # PATCH не затирает остальное

        assert client.delete(f"/api/v1/buildings/{body['id']}").status_code == 204
        assert client.get(f"/api/v1/buildings/{body['id']}").status_code == 404

    def test_duplicate_code(self, client, building):
        response = client.post(
            "/api/v1/buildings",
            json={"code": "A", "name": "Другой", "address": "адрес", "floors_count": 2},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DUPLICATE_CODE"

    @pytest.mark.parametrize("query", ["?page=0", "?page_size=100000", "?лишний=1"])
    def test_bad_query_params(self, client, admin, query):
        response = client.get(f"/api/v1/buildings{query}")
        assert response.status_code in (200, 400, 422)
        if response.status_code == 200:
            # page=0 приводится к 1, page_size обрезается по максимуму
            assert response.json()["page"] >= 1
            assert response.json()["page_size"] <= 200

    def test_no_traceback_leaks(self, client, admin):
        """ТЗ 4.1.6: наружу не уходят ни трассировка, ни текст SQL."""
        response = client.post("/api/v1/buildings", json={"code": "A"})
        assert response.status_code == 422
        text = response.text.lower()
        assert "traceback" not in text
        assert "select" not in text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_unknown_field_rejected(self, client, admin):
        response = client.post(
            "/api/v1/buildings",
            json={
                "code": "A",
                "name": "Корпус",
                "address": "адрес",
                "floors_count": 3,
                "объём": 100,
            },
        )
        assert response.status_code == 422

    def test_observer_can_read_but_not_write(self, client, session, building):
        make_user(session, "observer", Role.OBSERVER)
        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/login", json={"username": "observer", "password": "пароль-12345"}
        )
        assert client.get("/api/v1/buildings").status_code == 200
        response = client.post(
            "/api/v1/buildings",
            json={"code": "B", "name": "Второй", "address": "адрес", "floors_count": 2},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_buildings_require_login(self, client):
        assert client.get("/api/v1/buildings").status_code == 401
