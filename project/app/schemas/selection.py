"""Схема строки результата подбора аудитории."""

from __future__ import annotations

from decimal import Decimal

from pydantic import field_serializer

from app.schemas.common import OrmSchema
from app.schemas.room_type import RoomTypeOut


class SuitableRoomOut(OrmSchema):
    """Строка результата подбора аудитории."""

    id: int
    building_id: int
    number: str
    floor: int
    room_type_id: int
    area: Decimal
    seats: int
    volume: int
    room_type: RoomTypeOut
    #: Насколько мест больше, чем нужно группе. Отрицательное — перегруз (D2)
    seats_margin: int = 0
    overloaded: bool = False

    @field_serializer("area")
    def _area(self, value: Decimal) -> str:
        return f"{value:.2f}"
