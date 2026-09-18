"""Сборка приложения AudFond.

Общий файл: по правилам приёмки изменений меняется только по согласованию —
здесь подключаются маршрутизаторы всех участников, поэтому это и есть место,
где ветки чаще всего расходятся.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db
from app.config import Config, load_config
from app.context import get_request_id, new_request_id, set_request_id
from app.errors import ApiError
from app.logging_setup import configure_logging

__version__ = "0.1.0"

log = logging.getLogger("audfond")
access_log = logging.getLogger("audfond.access")


def error_response(status: int, code: str, message: str, details: dict | None = None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": get_request_id(),
        },
        headers={"X-Request-Id": get_request_id()},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = [
            {
                "field": ".".join(str(part) for part in err["loc"][1:]) or "body",
                "error": err["msg"],
            }
            for err in exc.errors()
        ]
        return error_response(
            422, "VALIDATION_ERROR", "Данные не прошли проверку", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        codes = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }
        messages = {
            401: "Требуется вход в систему",
            403: "Недостаточно прав для этой операции",
            404: "Адрес не найден",
            405: "Метод не поддерживается для этого адреса",
        }
        return error_response(
            exc.status_code,
            codes.get(exc.status_code, "HTTP_ERROR"),
            messages.get(exc.status_code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        # Трассировка уходит в журнал, наружу — только идентификатор запроса
        log.exception("Необработанное исключение", extra={"path": request.url.path})
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Внутренняя ошибка сервера. Сообщите идентификатор запроса администратору.",
        )


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    configure_logging(config.log_level, config.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_engine(config.database_url)
        log.info(
            "AudFond запущен",
            extra={"event": "startup", "version": __version__, "app_env": config.app_env},
        )
        yield
        # ТЗ 4.2: при остановке закрываем соединения с базой
        db.dispose_engine()
        log.info("AudFond остановлен", extra={"event": "shutdown"})

    app = FastAPI(
        title="AudFond — аудиторный фонд университета",
        description=(
            "HTTP API системы учёта аудиторного фонда. "
            "Техническое задание: А.В.00001-01 33 01-1."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.config = config

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-Id", "").strip()
        set_request_id(incoming or new_request_id())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = get_request_id()
        access_log.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    register_error_handlers(app)
    _register_routers(app)

    app.mount(
        "/static",
        StaticFiles(directory="app/web/static", check_dir=False),
        name="static",
    )
    return app


def _register_routers(app: FastAPI) -> None:
    from app.api.auth import router as auth_router
    from app.api.health import router as health_router
    from app.api.users import router as users_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)


app = None  # приложение создаётся фабрикой; см. wsgi.py и uvicorn app.main:build
