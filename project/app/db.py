"""Подключение к PostgreSQL и жизненный цикл сессии.

Движок создаётся один раз при старте. Сессия живёт ровно один HTTP-запрос:
FastAPI отдаёт её через зависимость, а по завершении запроса откатывает и
закрывает.

Коммит делает обработчик, а не зависимость — осознанно. Автокоммит в конце
запроса был бы ошибкой: ApiError перехватывается обработчиком исключений, до
зависимости исключение не доходит, и незавершённые изменения молча сохранились
бы вместе с ответом «операция отклонена».
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> Engine:
    global _engine, _session_factory
    _engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,  # разрыв соединения с БД не должен ронять запрос
        pool_size=5,
        max_overflow=5,
        future=True,
    )
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def dispose_engine() -> None:
    """Закрыть соединения при остановке (ТЗ 4.2, корректное завершение)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Движок базы не инициализирован: вызовите init_engine()")
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        raise RuntimeError("Фабрика сессий не готова: вызовите init_engine()")
    return _session_factory


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на один запрос."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def database_ready() -> tuple[bool, str]:
    """Проверка для /readyz: база отвечает?"""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - зависит от окружения
        return False, type(exc).__name__


def current_revision() -> str | None:
    """Ревизия миграций, накатанная на базу. None — таблицы alembic ещё нет."""
    with get_engine().connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if not exists:
            return None
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
