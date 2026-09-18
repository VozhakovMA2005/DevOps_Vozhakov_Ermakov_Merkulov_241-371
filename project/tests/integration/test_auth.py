"""Вход в систему, роли и защита от подбора пароля — ТЗ 4.1.1."""

from __future__ import annotations

import pytest

from app.models import Role
from tests.conftest import make_user

#: Адреса, закрытые входом. Проверка того, что каждый новый раздел API тоже
#: закрыт, живёт в тестах этого раздела — здесь только то, что уже есть.
CLOSED_PATHS = ["/api/v1/users", "/api/v1/auth/me"]


@pytest.mark.parametrize("path", CLOSED_PATHS)
def test_api_requires_login(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_sets_httponly_cookie(client, session):
    make_user(session, "engineer", Role.FUND_ADMIN)
    response = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "пароль-12345"}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_token_works_in_authorization_header(client, session):
    make_user(session, "service", Role.SERVICE)
    token = client.post(
        "/api/v1/auth/login", json={"username": "service", "password": "пароль-12345"}
    ).json()["access_token"]
    client.cookies.clear()
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_unknown_user_and_bad_password_look_the_same(client, session):
    make_user(session, "engineer", Role.FUND_ADMIN)
    unknown = client.post(
        "/api/v1/auth/login", json={"username": "никого", "password": "пароль-12345"}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "неверный-пароль"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"] == wrong.json()["error"]


def test_blocked_after_five_attempts(client, session):
    """ТЗ 4.1.1: временная блокировка после 5 неудачных попыток подряд."""
    make_user(session, "engineer", Role.FUND_ADMIN)
    for _ in range(4):
        response = client.post(
            "/api/v1/auth/login", json={"username": "engineer", "password": "мимо"}
        )
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    fifth = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "мимо"}
    )
    assert fifth.json()["error"]["code"] == "LOGIN_TEMPORARILY_BLOCKED"

    # Даже верный пароль теперь не пускает
    correct = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "пароль-12345"}
    )
    assert correct.status_code == 401
    assert correct.json()["error"]["code"] == "LOGIN_TEMPORARILY_BLOCKED"
    assert "locked_until" in correct.json()["error"]["details"]


def test_successful_login_resets_counter(client, session):
    make_user(session, "engineer", Role.FUND_ADMIN)
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"username": "engineer", "password": "мимо"})
    ok = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "пароль-12345"}
    )
    assert ok.status_code == 200

    from sqlalchemy import select

    from app.models import AppUser

    user = session.scalar(select(AppUser).where(AppUser.username == "engineer"))
    session.refresh(user)
    assert user.failed_attempts == 0
    assert user.last_login_at is not None


def test_logout_clears_cookie(client, admin):
    assert client.get("/api/v1/auth/me").status_code == 200
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_broken_token_is_rejected(client, admin):
    client.cookies.clear()
    response = client.get(
        "/api/v1/users", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_token_signed_by_another_key_is_rejected(client, admin):
    """Подделать токен без знания JWT_SECRET нельзя."""
    from app.security import create_token

    forged = create_token(
        user_id=1,
        username="admin",
        role="SYS_ADMIN",
        secret="чужой-ключ-подписи-1234567890",
        ttl_minutes=60,
    )
    client.cookies.clear()
    response = client.get("/api/v1/users", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_password_never_returned(client, admin, session):
    make_user(session, "engineer", Role.FUND_ADMIN)
    text = client.get("/api/v1/users").text
    assert "password" not in text
    assert "argon2" not in text.lower()


def test_only_sys_admin_manages_users(client, session):
    make_user(session, "engineer", Role.FUND_ADMIN)
    client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "пароль-12345"}
    )
    response = client.get("/api/v1/users")
    assert response.status_code == 403
    assert response.json()["error"]["details"]["your_role"] == "FUND_ADMIN"


def test_admin_cannot_disable_self(client, admin):
    me = client.get("/api/v1/auth/me").json()
    response = client.patch(f"/api/v1/users/{me['id']}", json={"is_active": False})
    assert response.status_code == 403
