"""Служебные адреса — ТЗ 4.1.1.

/healthz — приложение живо (базы не касается);
/readyz  — база доступна и ревизия миграций совпадает с ожидаемой;
/version — версия приложения и идентификатор коммита.

Эти три адреса доступны без входа в систему (ТЗ 4.6).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db

router = APIRouter(tags=["служебные"])


@router.get("/healthz", summary="Живость приложения")
def healthz(request: Request) -> dict[str, str]:
    return {"status": "ok", "instance": request.app.state.config.instance_id}


@router.get("/readyz", summary="Готовность: база и миграции")
def readyz(request: Request) -> JSONResponse:
    from app.main import __version__, error_response

    ok, detail = db.database_ready()
    if not ok:
        return error_response(503, "DB_UNAVAILABLE", f"База данных недоступна: {detail}")

    revision = db.current_revision()
    if revision is None:
        return error_response(
            503, "MIGRATIONS_NOT_APPLIED", "Миграции не применены: выполните make migrate"
        )

    migration_config = AlembicConfig()
    migration_config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
    )
    expected = ScriptDirectory.from_config(migration_config).get_heads()
    if expected != [revision]:
        return error_response(
            503, "MIGRATIONS_MISMATCH", "Ревизия базы не совпадает с ревизией приложения"
        )

    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "checks": {"database": "ok", "migrations": f"ok: {revision}"},
        }
    )


@router.get("/version", summary="Версия приложения и коммит")
def version(request: Request) -> dict[str, str]:
    from app.main import __version__

    config = request.app.state.config
    return {
        "version": __version__,
        "commit": config.git_commit,
        "app_env": config.app_env,
        "instance": config.instance_id,
    }
