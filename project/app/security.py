"""Пароли и токены доступа — ТЗ 4.1.1.

Пароль хранится только как хэш Argon2id с индивидуальной солью: соль argon2-cffi
генерирует сам и кладёт внутрь строки хэша, отдельного поля для неё не нужно.

Токен — JWT, подписанный ключом из переменной окружения JWT_SECRET. Срок жизни
ограничен. В вебе токен уезжает в cookie с HttpOnly и SameSite, в продуктивной
среде — ещё и Secure; для API принимается в заголовке Authorization: Bearer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

ALGORITHM = "HS256"
COOKIE_NAME = "audfond_token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля. Любой сбой сверки — это «не подошёл», а не 500."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:  # pragma: no cover — ветка достижима только на устаревшем хэше
        return True


def create_token(
    *, user_id: int, username: str, role: str, secret: str, ttl_minutes: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> dict[str, Any] | None:
    """Возвращает полезную нагрузку или None, если токен негоден."""
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
