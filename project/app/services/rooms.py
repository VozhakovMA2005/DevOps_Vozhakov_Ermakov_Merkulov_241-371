"""Помещения и правило D5 — ключевое правило предметной области этапа 1.

D5: суммарное число посадочных мест (для обучающихся и сотрудников) не должно
превышать нормативную вместимость помещения, равную рабочей площади, делённой
на норму площади на одного человека для типа помещения, с округлением вниз.

Правило нельзя выразить ограничением базы: норма лежит в другой таблице
(room_type), а CHECK в PostgreSQL не умеет обращаться к другим таблицам.
Поэтому проверка живёт в сервисном слое и срабатывает в трёх местах: при
заведении карточки, при её правке и при внесении нового обмера.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.errors import FloorOutOfRange, HasDependents, RuleD5
from app.models import (
    Building,
    Department,
    MeasurementSource,
    Room,
    RoomMeasurement,
    RoomType,
)
from app.services.common import get_or_404, get_related_or_409
from app.services.paging import commit, flush


def check_floor(building: Building, floor: int) -> None:
    """Этаж должен существовать в этом корпусе."""
    if not building.floor_allowed(floor):
        raise FloorOutOfRange(
            f"В корпусе {building.code} нет этажа {floor}. "
            f"Допустимые этажи: {building.floors_hint()}",
            details={
                "building_id": building.id,
                "floor": floor,
                "allowed": building.floors_hint(),
            },
        )


def check_rule_d5(room_type: RoomType, area: Decimal, seats: int, staff_seats: int) -> None:
    """Правило D5. Норма не задана — проверять нечем, правило не применяется."""
    capacity = room_type.normative_capacity(area)
    if capacity is None:
        return
    total = seats + staff_seats
    if total > capacity:
        raise RuleD5(
            f"Нормативная вместимость помещения — {capacity} чел. "
            f"(площадь {area} м² / норма {room_type.area_norm} м² на человека), "
            f"а мест указано {total}",
            details={
                "rule": "D5",
                "room_type_code": room_type.code,
                "area": str(area),
                "area_norm": str(room_type.area_norm),
                "normative_capacity": capacity,
                "requested_total_seats": total,
                "excess": total - capacity,
            },
        )


def create(session: Session, payload: dict[str, Any], user_id: int | None = None) -> Room:
    building = get_related_or_409(session, Building, payload["building_id"], "building_id")
    room_type = get_related_or_409(session, RoomType, payload["room_type_id"], "room_type_id")
    if payload.get("department_id") is not None:
        get_related_or_409(session, Department, payload["department_id"], "department_id")

    check_floor(building, payload["floor"])
    check_rule_d5(
        room_type,
        payload["area"],
        payload.get("seats", 0),
        payload.get("staff_seats", 0),
    )

    room = Room(**payload)
    session.add(room)
    flush(session)

    # История обмеров начинается с первых значений карточки: иначе в истории
    # появится разрыв, и неоткуда будет узнать, с чего помещение начиналось
    session.add(
        RoomMeasurement(
            room_id=room.id,
            area=room.area,
            seats=room.seats,
            staff_seats=room.staff_seats,
            measured_on=date.today(),
            measured_by_id=user_id,
            source=MeasurementSource.INITIAL,
            note="Значения при заведении карточки помещения",
        )
    )

    commit(session)
    session.refresh(room)
    return room


def update(session: Session, room_id: int, changes: dict[str, Any]) -> Room:
    room = get_or_404(session, Room, room_id)

    room_type = room.room_type
    if changes.get("room_type_id") is not None:
        room_type = get_related_or_409(
            session, RoomType, changes["room_type_id"], "room_type_id"
        )
    if "department_id" in changes and changes["department_id"] is not None:
        get_related_or_409(session, Department, changes["department_id"], "department_id")
    if changes.get("floor") is not None:
        check_floor(room.building, changes["floor"])

    area = changes.get("area") or room.area
    seats = room.seats if changes.get("seats") is None else changes["seats"]
    staff_seats = (
        room.staff_seats if changes.get("staff_seats") is None else changes["staff_seats"]
    )
    check_rule_d5(room_type, area, seats, staff_seats)

    for field, value in changes.items():
        setattr(room, field, value)
    commit(session)
    session.refresh(room)
    return room


def delete(session: Session, room_id: int) -> None:
    room = get_or_404(session, Room, room_id)
    measurements = session.scalar(
        select(func.count())
        .select_from(RoomMeasurement)
        .where(RoomMeasurement.room_id == room_id)
    )
    if measurements:
        raise HasDependents(
            f"У помещения {room.number} есть история обмеров ({measurements}), "
            "удаление запрещено",
            details={"room_id": room_id, "measurements_count": int(measurements)},
        )
    session.delete(room)
    commit(session)


def query(
    *,
    building_id: int | None = None,
    floor: int | None = None,
    room_type_id: int | None = None,
    department_id: int | None = None,
    is_usable: bool | None = None,
    area_min: Decimal | None = None,
    area_max: Decimal | None = None,
    q: str | None = None,
) -> Select:
    statement = select(Room).order_by(Room.building_id, Room.floor, Room.number)
    if building_id is not None:
        statement = statement.where(Room.building_id == building_id)
    if floor is not None:
        statement = statement.where(Room.floor == floor)
    if room_type_id is not None:
        statement = statement.where(Room.room_type_id == room_type_id)
    if department_id is not None:
        statement = statement.where(Room.department_id == department_id)
    if is_usable is not None:
        statement = statement.where(Room.is_usable.is_(is_usable))
    if area_min is not None:
        statement = statement.where(Room.area >= area_min)
    if area_max is not None:
        statement = statement.where(Room.area <= area_max)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(func.lower(Room.number).like(pattern), func.lower(Room.note).like(pattern))
        )
    return statement


def floors_of(session: Session, building_id: int) -> list[dict[str, Any]]:
    """Этажи корпуса с числом помещений — для навигации «корпус → этаж»."""
    rows = session.execute(
        select(Room.floor, func.count(Room.id))
        .where(Room.building_id == building_id)
        .group_by(Room.floor)
        .order_by(Room.floor)
    ).all()
    return [{"floor": floor, "rooms_count": int(count)} for floor, count in rows]
