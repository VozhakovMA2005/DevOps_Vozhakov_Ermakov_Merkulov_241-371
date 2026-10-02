"""Вход, выход и текущий пользователь — ТЗ 4.1.1."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.deps import AppConfig, CurrentUser, DbSession
from app.models import ROLE_TITLES
from app.schemas import LoginRequest, UserOut
from app.security import COOKIE_NAME
from app.services import auth as service

router = APIRouter(prefix="/api/v1/auth", tags=["аутентификация"])


def set_auth_cookie(
    response: Response, token: str, config: AppConfig, ttl_seconds: int
) -> None:
    """Токен в cookie: HttpOnly и SameSite всегда, Secure — по настройке.

    Secure вынесен в COOKIE_SECURE, а не привязан к APP_ENV: браузер не
    сохраняет Secure-cookie, пришедшую по http, и вход тогда молча не
    срабатывает. На стенде без TLS ставится false, за прокси с TLS — true.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure,
        path="/",
    )


@router.post("/login", summary="Вход по логину и паролю")
def login(payload: LoginRequest, response: Response, session: DbSession, config: AppConfig):
    user = service.authenticate(
        session, config, payload.username, payload.password.get_secret_value()
    )
    token, ttl = service.issue_token(config, user)
    set_auth_cookie(response, token, config, ttl)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl}


@router.post("/logout", summary="Выход из системы")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserOut, summary="Текущий пользователь")
def me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        role_title=ROLE_TITLES[user.role],
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )
