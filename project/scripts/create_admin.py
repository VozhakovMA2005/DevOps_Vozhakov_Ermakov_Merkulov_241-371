"""Создание первого администратора — ТЗ 4.1.1.

Логин и пароль берутся из переменных окружения, а не из аргументов командной
строки: аргументы видны в истории оболочки и в списке процессов.

    ADMIN_USERNAME=admin ADMIN_PASSWORD=... python scripts/create_admin.py

Команда идемпотентна: если пользователь уже есть, она ничего не меняет и
сообщает об этом.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import ConfigError, load_config
from app.db import init_engine, session_factory
from app.models import AppUser, Role
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8


def main() -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"Конфигурация не годится: {error}", file=sys.stderr)
        return 2

    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    full_name = os.getenv("ADMIN_FULL_NAME", "Администратор системы").strip()

    if not username or not password:
        print(
            "Задайте ADMIN_USERNAME и ADMIN_PASSWORD в окружении (см. .env.example)",
            file=sys.stderr,
        )
        return 2
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Пароль короче {MIN_PASSWORD_LENGTH} символов", file=sys.stderr)
        return 2
    if password.startswith("CHANGE_ME"):
        print("Пароль из примера использовать нельзя", file=sys.stderr)
        return 2

    init_engine(config.database_url)
    with session_factory()() as session:
        existing = session.scalar(select(AppUser).where(AppUser.username == username))
        if existing is not None:
            print(f"Пользователь {username} уже есть, ничего не меняю")
            return 0

        session.add(
            AppUser(
                username=username,
                full_name=full_name,
                password_hash=hash_password(password),
                role=Role.SYS_ADMIN,
                is_active=True,
            )
        )
        session.commit()

    print(f"Создан администратор системы: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
