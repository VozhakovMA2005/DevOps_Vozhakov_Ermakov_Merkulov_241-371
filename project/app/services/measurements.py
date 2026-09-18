"""История обмеров помещений — ТЗ 4.1.1.

Обмер — единственный штатный способ изменить площадь помещения. Каждая запись
сохраняет площадь и вместимость на дату обмера, автора и источник данных.
История не переписывается: ошибочный обмер исправляется новым обмером, а не
правкой старого.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import HistoryImmutable
from app.models import AppUser, MeasurementSource, Room, RoomMeasurement
from app.services.common import get_or_404, translate_integrity_error
from app.services.rooms import check_rule_d5


def create(
    session: Session, room_id: int, payload: dict[str, Any], user: AppUser | None
) -> RoomMeasurement:
    """Новый обмер: проверяем правило D5 и переносим значения в карточку."""
    room = get_or_404(session, Room, room_id)

    check_rule_d5(room.room_type, payload["area"], payload["seats"], payload["staff_seats"])

    measurement = RoomMeasurement(
        room_id=room.id,
        measured_by_id=user.id if user else None,
        source=MeasurementSource.MANUAL,
        **payload,
    )
    session.add(measurement)

    # Карточка помещения всегда показывает последний обмер
    room.area = payload["area"]
    room.seats = payload["seats"]
    room.staff_seats = payload["staff_seats"]

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise translate_integrity_error(error) from error
    session.refresh(room)
    return measurement


def delete(session: Session, measurement_id: int) -> None:
    """История обмеров не удаляется (ТЗ 4.1.1: ведение истории изменений)."""
    get_or_404(session, RoomMeasurement, measurement_id)
    raise HistoryImmutable(
        "История обмеров не удаляется. Чтобы исправить данные, внесите новый обмер",
        details={"measurement_id": measurement_id},
    )


def query(room_id: int) -> Select:
    return (
        select(RoomMeasurement)
        .where(RoomMeasurement.room_id == room_id)
        .order_by(RoomMeasurement.measured_on.desc(), RoomMeasurement.id.desc())
    )
