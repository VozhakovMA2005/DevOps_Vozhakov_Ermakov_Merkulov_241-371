"""Служебные адреса и единый формат ошибки."""

from __future__ import annotations


def test_healthz_is_open(client):
    """Служебные адреса доступны без входа (ТЗ 4.6)."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_migrations(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"].startswith("ok: ")


def test_version_reports_commit(client):
    body = client.get("/version").json()
    assert body["version"]
    assert "commit" in body
    assert body["app_env"] == "test"


def test_request_id_in_header_and_body(client):
    response = client.get("/api/v1/нет-такого-адреса")
    assert response.status_code == 404
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-Id"]
    assert set(body["error"]) == {"code", "message", "details"}


def test_incoming_request_id_is_kept(client):
    """Свой идентификатор запроса позволяет связать журналы систем."""
    mine = "0123456789abcdef0123456789abcdef"
    response = client.get("/healthz", headers={"X-Request-Id": mine})
    assert response.headers["X-Request-Id"] == mine


def test_unknown_path_is_json_not_html(client):
    response = client.get("/api/v1/нет-такого")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
