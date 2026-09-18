"""Справочник типов помещений с нормой площади на человека (правило D5)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import HasDependents
from app.models import Room, RoomType
from app.services.common import get_or_404
from app.services.paging import commit


def create_room_type(session: Session, payload: dict[str, Any]) -> RoomType:
    room_type = RoomType(**payload)
    session.add(room_type)
    commit(session)
    return room_type


def update_room_type(session: Session, room_type_id: int, changes: dict[str, Any]) -> RoomType:
    room_type = get_or_404(session, RoomType, room_type_id)
    for field, value in changes.items():
        setattr(room_type, field, value)
    commit(session)
    return room_type


def delete_room_type(session: Session, room_type_id: int) -> None:
    room_type = get_or_404(session, RoomType, room_type_id)
    rooms = session.scalar(
        select(func.count()).select_from(Room).where(Room.room_type_id == room_type_id)
    )
    if rooms:
        raise HasDependents(
            f"Тип {room_type.code} используется помещениями ({rooms})",
            details={"room_type_id": room_type_id, "rooms_count": int(rooms)},
        )
    session.delete(room_type)
    commit(session)
