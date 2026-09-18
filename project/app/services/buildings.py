"""Корпуса университета."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.errors import HasDependents
from app.models import Building, Room
from app.services.common import get_or_404
from app.services.paging import commit


def create_building(session: Session, payload: dict[str, Any]) -> Building:
    building = Building(**payload)
    session.add(building)
    commit(session)
    return building


def update_building(session: Session, building_id: int, changes: dict[str, Any]) -> Building:
    building = get_or_404(session, Building, building_id)
    for field, value in changes.items():
        setattr(building, field, value)
    commit(session)
    return building


def delete_building(session: Session, building_id: int) -> None:
    building = get_or_404(session, Building, building_id)
    rooms = session.scalar(
        select(func.count()).select_from(Room).where(Room.building_id == building_id)
    )
    if rooms:
        raise HasDependents(
            f"В корпусе {building.code} есть помещения ({rooms}), удаление запрещено",
            details={"building_id": building_id, "rooms_count": int(rooms)},
        )
    session.delete(building)
    commit(session)


def query_buildings(q: str | None) -> Select:
    statement = select(Building).order_by(Building.code)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Building.name).like(pattern),
                func.lower(Building.code).like(pattern),
                func.lower(Building.address).like(pattern),
            )
        )
    return statement
