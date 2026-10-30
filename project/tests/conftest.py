"""Фикстуры. Тесты идут на настоящем PostgreSQL.

Вычисляемый столбец, CHECK-ограничения и перечисления на SQLite не
воспроизводятся, а проверяется здесь именно они. Для каждого прогона
создаётся отдельная база, после — удаляется.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN_DSN = os.getenv("TEST_ADMIN_DSN", "postgresql://postgres@127.0.0.1:5432/postgres")
TEST_SECRET = "тестовый-ключ-подписи-достаточной-длины-1234567890"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    psycopg = pytest.importorskip("psycopg")
    name = f"audfond_test_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except Exception as exc:  # pragma: no cover — ветка для окружения без базы
        pytest.skip(f"PostgreSQL недоступен ({exc})")

    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')

    target = ADMIN_DSN.rsplit("/", 1)[0] + f"/{name}"
    url = f"postgresql+psycopg://{target.split('://', 1)[1]}"

    # Схему накатывает Alembic — то же, что произойдёт в бою
    result = subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover — ветка для окружения без базы
        pytest.fail(f"Миграции не применились:\n{result.stderr}")

    try:
        yield url
    finally:
        from app import db as db_module

        db_module.dispose_engine()
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cleanup:
            cleanup.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def app(database_url: str, monkeypatch: pytest.MonkeyPatch):
    # Настройки разработчика из .env не должны влиять на тесты: окружение
    # задаётся здесь целиком (пункт 6 задания — изоляция конфигурации)
    for name in ("COOKIE_SECURE", "LOG_FORMAT", "PAGE_SIZE_DEFAULT", "PAGE_SIZE_MAX"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from app.config import load_config
    from app.main import create_app

    application = create_app(load_config())

    # Каждый тест начинает с чистых данных; справочник типов остаётся —
    # он приходит миграцией и является частью схемы
    from sqlalchemy import text

    from app.db import get_engine, init_engine

    init_engine(database_url)
    tables = [
        "room_measurement",
        "room",
        "discipline_room_type",
        "discipline",
        "department",
        "building",
        "app_user",
    ]
    with get_engine().begin() as connection:
        existing = [
            name
            for name in tables
            if connection.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{name}"}
            ).scalar()
        ]
        if existing:
            connection.execute(
                text(f"TRUNCATE {', '.join(existing)} RESTART IDENTITY CASCADE")
            )
    return application


@pytest.fixture
def client(app) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(app) -> Iterator:
    from app.db import session_factory

    sess = session_factory()()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


def make_user(session, username: str, role, password: str = "пароль-12345") -> int:
    from app.models import AppUser
    from app.security import hash_password

    user = AppUser(
        username=username,
        full_name=f"Пользователь {username}",
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    session.commit()
    return user.id


@pytest.fixture
def admin(client, session):
    """Вошедший администратор системы — состояние по умолчанию для тестов."""
    from app.models import Role

    make_user(session, "admin", Role.SYS_ADMIN)
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "пароль-12345"}
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.fixture
def room_types(client, admin) -> dict[str, dict]:
    return {row["code"]: row for row in client.get("/api/v1/room-types").json()}


@pytest.fixture
def building(client, admin) -> dict:
    response = client.post(
        "/api/v1/buildings",
        json={
            "code": "A",
            "name": "Главный корпус",
            "address": "ул. Чехова, 2",
            "floors_count": 5,
            "has_basement": True,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def department(client, admin) -> dict:
    response = client.post(
        "/api/v1/departments", json={"code": "KAF-VT", "name": "Кафедра ВТ"}
    )
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def room(client, building, room_types) -> dict:
    """Семинарская 62.50 м² на 24 места: норматив D5 ровно 25, соблюдён."""
    response = client.post(
        "/api/v1/rooms",
        json={
            "building_id": building["id"],
            "number": "201",
            "floor": 2,
            "room_type_id": room_types["SEMINAR"]["id"],
            "area": "62.50",
            "seats": 24,
            "staff_seats": 1,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def discipline(client, room_types) -> dict:
    response = client.post(
        "/api/v1/disciplines",
        json={
            "code": "IB-01",
            "name": "Основы информационной безопасности",
            "allowed_room_type_ids": [room_types["SEMINAR"]["id"]],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def area(value: str) -> Decimal:
    return Decimal(value)
