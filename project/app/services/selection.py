"""Подбор аудитории под занятие — правила D1, D2, D6 (ТЗ 4.1.4).

Сценарий S из подраздела 3.4: «подбор аудитории под занятие группы». На этапе 1
это подбор кандидатов; автоматическое распределение по слогам расписания идёт
этапом 5.

Фильтры применяются в том же порядке, в каком правила записаны в ТЗ:
  D6 — непригодные помещения не рассматриваются вовсе;
  D1 — тип помещения должен быть разрешён дисциплине матрицей допустимости;
  D2 — мест для обучающихся должно хватить на группу; перегруз допускается
       только при явно включённом параметре и помечается в ответе.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import RuleD1, RuleD2, RuleD6
from app.models import Discipline, Room
from app.services.common import get_or_404


def suitable_rooms(
    session: Session,
    *,
    discipline_id: int,
    group_size: int,
    building_id: int | None = None,
    allow_overload: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    discipline = get_or_404(session, Discipline, discipline_id)
    allowed_type_ids = [item.id for item in discipline.allowed_room_types]

    result: dict[str, Any] = {
        "discipline": {"id": discipline.id, "code": discipline.code, "name": discipline.name},
        "group_size": group_size,
        "allow_overload": allow_overload,
        "items": [],
        "rejected": {"D1_not_allowed": 0, "D2_too_small": 0, "D6_not_usable": 0},
    }

    if not allowed_type_ids:
        # Матрица допустимости для дисциплины пуста — подбирать не из чего
        result["reason"] = (
            f"Для дисциплины {discipline.code} не задан ни один разрешённый тип "
            "помещения (матрица допустимости пуста, правило D1)"
        )
        return result

    statement = select(Room).order_by(Room.seats, Room.area)
    if building_id is not None:
        statement = statement.where(Room.building_id == building_id)

    for room in session.scalars(statement):
        if not room.is_usable:  # D6
            result["rejected"]["D6_not_usable"] += 1
            continue
        if room.room_type_id not in allowed_type_ids:  # D1
            result["rejected"]["D1_not_allowed"] += 1
            continue
        margin = room.seats - group_size
        if margin < 0 and not allow_overload:  # D2
            result["rejected"]["D2_too_small"] += 1
            continue
        result["items"].append(
            {
                "id": room.id,
                "building_id": room.building_id,
                "number": room.number,
                "floor": room.floor,
                "room_type_id": room.room_type_id,
                "room_type": room.room_type,
                "area": room.area,
                "seats": room.seats,
                "volume": room.volume,
                "seats_margin": margin,
                "overloaded": margin < 0,
            }
        )
        if len(result["items"]) >= limit:
            break

    return result


def check_assignment(
    session: Session, room: Room, discipline_id: int, group_size: int
) -> None:
    """Проверка одного назначения по D6, D1 и D2 — для этапа распределения."""
    if not room.is_usable:
        raise RuleD6(
            f"Помещение {room.number} отмечено как непригодное к эксплуатации",
            details={"rule": "D6", "room_id": room.id},
        )
    discipline = get_or_404(session, Discipline, discipline_id)
    if not discipline.allows(room.room_type_id):
        allowed = ", ".join(item.code for item in discipline.allowed_room_types) or "—"
        raise RuleD1(
            f"Дисциплина {discipline.code} не разрешена в помещении типа "
            f"{room.room_type.code}. Разрешённые типы: {allowed}",
            details={
                "rule": "D1",
                "discipline_code": discipline.code,
                "room_type_code": room.room_type.code,
                "allowed_room_types": [item.code for item in discipline.allowed_room_types],
            },
        )
    if group_size > room.seats:
        raise RuleD2(
            f"В помещении {room.number} мест для обучающихся {room.seats}, "
            f"а в группе {group_size}",
            details={
                "rule": "D2",
                "room_id": room.id,
                "seats": room.seats,
                "group_size": group_size,
                "excess": group_size - room.seats,
            },
        )
