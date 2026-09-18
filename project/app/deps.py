"""Зависимости FastAPI: конфигурация, сессия, текущий пользователь, роли.

ТЗ 4.6: доступ ко всем функциям, кроме страницы входа и служебных адресов
/healthz, /readyz и /version, предоставляется только аутентифицированным
пользователям. Здесь это и обеспечивается — точка, через которую проходит
каждый защищённый обработчик.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.db import get_session
from app.errors import Forbidden, Unauthenticated
from app.models import WRITE_ROLES, AppUser, Role
from app.security import COOKIE_NAME, decode_token


def get_config(request: Request) -> Config:
    return request.app.state.config


DbSession = Annotated[Session, Depends(get_session)]
AppConfig = Annotated[Config, Depends(get_config)]


def _token_from(request: Request) -> str | None:
    """Токен принимается из заголовка (API) и из cookie (веб-страницы)."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request, session: DbSession, config: AppConfig) -> AppUser:
    token = _token_from(request)
    if not token:
        raise Unauthenticated()

    payload = decode_token(token, config.jwt_secret)
    if payload is None:
        raise Unauthenticated("Токен доступа недействителен или истёк")

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise Unauthenticated("Токен доступа повреждён") from None

    user = session.get(AppUser, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Учётная запись недоступна")
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


def optional_user(request: Request, session: DbSession, config: AppConfig) -> AppUser | None:
    """Для страниц: не вошёл — не ошибка, а переход на форму входа."""
    try:
        return current_user(request, session, config)
    except Unauthenticated:
        return None


MaybeUser = Annotated[AppUser | None, Depends(optional_user)]


def require_roles(*roles: Role):
    """Зависимость-проверка роли: 403, если роль не подходит (ТЗ 3.3)."""

    allowed = set(roles)

    def dependency(user: CurrentUser) -> AppUser:
        if user.role not in allowed:
            raise Forbidden(
                "Операция доступна ролям: "
                + ", ".join(role.label for role in sorted(allowed, key=lambda r: r.value)),
                details={
                    "your_role": user.role.value,
                    "allowed_roles": [role.value for role in allowed],
                },
            )
        return user

    return dependency


def require_write(user: CurrentUser) -> AppUser:
    """Наблюдатель и внешняя система данные не меняют."""
    if user.role not in WRITE_ROLES:
        raise Forbidden(
            "Ваша роль даёт только право просмотра",
            details={"your_role": user.role.value},
        )
    return user


WriteUser = Annotated[AppUser, Depends(require_write)]
SysAdmin = Annotated[AppUser, Depends(require_roles(Role.SYS_ADMIN))]
FundAdmin = Annotated[AppUser, Depends(require_roles(Role.SYS_ADMIN, Role.FUND_ADMIN))]
Dispatcher = Annotated[AppUser, Depends(require_roles(Role.SYS_ADMIN, Role.DISPATCHER))]


def page_params(
    config: AppConfig, page: int = 1, page_size: int | None = None
) -> Iterator[tuple[int, int]]:
    yield max(page, 1), min(page_size or config.page_size_default, config.page_size_max)
