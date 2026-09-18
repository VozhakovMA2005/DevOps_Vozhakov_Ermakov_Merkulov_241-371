"""Дисциплины и матрица допустимости «дисциплина — тип помещения» (D1)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Discipline, RoomType
from app.services.common import get_or_404, get_related_or_409
from app.services.paging import commit


def _set_matrix(session: Session, discipline: Discipline, type_ids: list[int]) -> None:
    types = []
    for type_id in dict.fromkeys(type_ids):
        types.append(get_related_or_409(session, RoomType, type_id, "allowed_room_type_ids"))
    discipline.allowed_room_types = types


def create_discipline(session: Session, payload: dict[str, Any]) -> Discipline:
    type_ids = payload.pop("allowed_room_type_ids", [])
    discipline = Discipline(**payload)
    session.add(discipline)
    _set_matrix(session, discipline, type_ids)
    commit(session)
    return discipline


def update_discipline(
    session: Session, discipline_id: int, changes: dict[str, Any]
) -> Discipline:
    discipline = get_or_404(session, Discipline, discipline_id)
    type_ids = changes.pop("allowed_room_type_ids", None)
    for field, value in changes.items():
        setattr(discipline, field, value)
    if type_ids is not None:
        _set_matrix(session, discipline, type_ids)
    commit(session)
    return discipline


def delete_discipline(session: Session, discipline_id: int) -> None:
    discipline = get_or_404(session, Discipline, discipline_id)
    session.delete(discipline)
    commit(session)


def query_disciplines(q: str | None) -> Select:
    statement = select(Discipline).order_by(Discipline.code)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Discipline.name).like(pattern),
                func.lower(Discipline.code).like(pattern),
            )
        )
    return statement
