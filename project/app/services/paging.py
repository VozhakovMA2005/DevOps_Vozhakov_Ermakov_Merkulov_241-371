"""Общее для сервисов справочников: коммит и постраничный вывод."""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.common import translate_integrity_error


def commit(session: Session) -> None:
    """Коммит, который превращает ограничение БД в понятный отказ."""
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise translate_integrity_error(error) from error


def flush(session: Session) -> None:
    """То же для flush: нарушение уникальности всплывает уже здесь, если после
    вставки нужно узнать идентификатор записи."""
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise translate_integrity_error(error) from error


def paginate(
    session: Session, statement: Select, page: int, page_size: int
) -> tuple[list, int]:
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(session.scalars(statement.limit(page_size).offset((page - 1) * page_size)))
    return rows, total
