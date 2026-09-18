"""Вход в систему, учётные записи и защита от подбора пароля — ТЗ 4.1.1."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Config
from app.errors import (
    AccountDisabled,
    Forbidden,
    InvalidCredentials,
    LoginBlocked,
)
from app.models import AppUser, Role
from app.security import create_token, hash_password, needs_rehash, verify_password
from app.services.common import get_or_404, translate_integrity_error

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def authenticate(session: Session, config: Config, username: str, password: str) -> AppUser:
    """Проверка логина и пароля со счётчиком неудачных попыток.

    Сообщение об отказе одинаковое и для неизвестного логина, и для неверного
    пароля: иначе точка входа превращается в справочник существующих учёток.
    """
    user = session.scalar(select(AppUser).where(AppUser.username == username))

    if user is None:
        log.warning(
            "Отказ во входе", extra={"event": "login_failed", "reason": "unknown_user"}
        )
        raise InvalidCredentials()

    if user.locked_until is not None and user.locked_until > _now():
        log.warning(
            "Вход заблокирован",
            extra={"event": "login_blocked", "user_id": user.id},
        )
        raise LoginBlocked(
            "Вход временно заблокирован из-за неудачных попыток. "
            f"Повторите после {user.locked_until:%H:%M}",
            details={"locked_until": user.locked_until.isoformat()},
        )

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= config.login_max_attempts:
            user.locked_until = _now() + timedelta(minutes=config.login_lock_minutes)
            user.failed_attempts = 0
            session.commit()
            log.warning(
                "Учётная запись временно заблокирована",
                extra={"event": "login_locked", "user_id": user.id},
            )
            raise LoginBlocked(
                "Слишком много неудачных попыток. "
                f"Вход заблокирован на {config.login_lock_minutes} минут",
                details={"locked_until": user.locked_until.isoformat()},
            )
        session.commit()
        log.warning(
            "Отказ во входе",
            extra={"event": "login_failed", "user_id": user.id, "reason": "bad_password"},
        )
        raise InvalidCredentials()

    if not user.is_active:
        log.warning("Вход заблокированной учётной записи", extra={"user_id": user.id})
        raise AccountDisabled()

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    session.commit()
    log.info("Вход выполнен", extra={"event": "login_ok", "user_id": user.id})
    return user


def issue_token(config: Config, user: AppUser) -> tuple[str, int]:
    token = create_token(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        secret=config.jwt_secret,
        ttl_minutes=config.jwt_ttl_minutes,
    )
    return token, config.jwt_ttl_minutes * 60


def create_user(session: Session, payload: dict) -> AppUser:
    password = payload.pop("password")
    user = AppUser(
        **payload,
        password_hash=hash_password(
            password.get_secret_value() if hasattr(password, "get_secret_value") else password
        ),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise translate_integrity_error(error) from error
    log.info("Создан пользователь", extra={"event": "user_created", "user_id": user.id})
    return user


def update_user(session: Session, user_id: int, changes: dict, actor: AppUser) -> AppUser:
    user = get_or_404(session, AppUser, user_id)

    if "password" in changes and changes["password"] is not None:
        secret = changes.pop("password")
        user.password_hash = hash_password(
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
        )
        user.failed_attempts = 0
        user.locked_until = None

    if "is_active" in changes and changes["is_active"] is False and user.id == actor.id:
        raise Forbidden("Нельзя заблокировать собственную учётную запись")
    if "role" in changes and changes["role"] is not None and user.id == actor.id:
        raise Forbidden("Нельзя сменить роль собственной учётной записи")

    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise translate_integrity_error(error) from error
    return user


def count_admins(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.role == Role.SYS_ADMIN)
        )
        or 0
    )
