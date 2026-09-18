"""Помещения, обмеры и подбор аудитории."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.deps import CurrentUser, DbSession, WriteUser, page_params
from app.errors import InvalidQueryParam
from app.models import Building, Room
from app.schemas import (
    BuildingOut,
    RoomCreate,
    RoomOut,
    RoomUpdate,
    page_envelope,
)
from app.services import rooms as service
from app.services.common import changed_fields, get_or_404
from app.services.paging import paginate

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/rooms", tags=["помещения"])
#: Навигация «корпус → этаж» опирается на помещения, поэтому обработчик
#: живёт здесь, а не в модуле корпусов
buildings_router = APIRouter(prefix="/api/v1/buildings", tags=["корпуса"])


def _decimal(name: str, raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise InvalidQueryParam(
            f"Параметр {name} должен быть числом, получено: {raw!r}",
            details={"param": name, "value": raw},
        ) from None


# Статические адреса объявляются раньше /{room_id}, иначе «suitable»
# будет разобрано как идентификатор помещения


@router.get("", summary="Список помещений с фильтрами")
def list_rooms(
    session: DbSession,
    user: CurrentUser,
    pagination: Pagination,
    building_id: int | None = None,
    floor: int | None = None,
    room_type_id: int | None = None,
    department_id: int | None = None,
    is_usable: bool | None = None,
    area_min: str | None = None,
    area_max: str | None = None,
    q: str | None = Query(default=None, max_length=100),
):
    page, page_size = pagination
    statement = service.query(
        building_id=building_id,
        floor=floor,
        room_type_id=room_type_id,
        department_id=department_id,
        is_usable=is_usable,
        area_min=_decimal("area_min", area_min),
        area_max=_decimal("area_max", area_max),
        q=q,
    )
    rows, total = paginate(session, statement, page, page_size)
    return page_envelope([RoomOut.model_validate(r) for r in rows], total, page, page_size)


@router.post("", status_code=201, summary="Завести карточку помещения")
def create_room(payload: RoomCreate, session: DbSession, user: WriteUser):
    room = service.create(session, payload.model_dump(), user.id)
    return RoomOut.model_validate(room)


@router.get("/{room_id}", summary="Карточка помещения")
def read_room(room_id: int, session: DbSession, user: CurrentUser):
    return RoomOut.model_validate(get_or_404(session, Room, room_id))


@router.patch("/{room_id}", summary="Изменить карточку помещения")
def update_room(room_id: int, payload: RoomUpdate, session: DbSession, user: WriteUser):
    return RoomOut.model_validate(service.update(session, room_id, changed_fields(payload)))


@router.delete(
    "/{room_id}", status_code=204, response_class=Response, summary="Удалить помещение"
)
def delete_room(room_id: int, session: DbSession, user: WriteUser):
    service.delete(session, room_id)


@buildings_router.get("/{building_id}/floors", summary="Этажи корпуса с числом помещений")
def building_floors(building_id: int, session: DbSession, user: CurrentUser):
    building = get_or_404(session, Building, building_id)
    return {
        "building": BuildingOut.model_validate(building),
        "floors": service.floors_of(session, building_id),
    }
