"""Справочник типов помещений с нормой площади на человека."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.deps import CurrentUser, DbSession, WriteUser, page_params
from app.models import RoomType
from app.schemas import RoomTypeCreate, RoomTypeOut, RoomTypeUpdate
from app.services import room_types as service
from app.services.common import changed_fields

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/room-types", tags=["типы помещений"])


@router.get("", summary="Справочник типов помещений")
def list_room_types(session: DbSession, user: CurrentUser) -> list[RoomTypeOut]:
    from sqlalchemy import select

    rows = session.scalars(select(RoomType).order_by(RoomType.code)).all()
    return [RoomTypeOut.model_validate(row) for row in rows]


@router.post("", status_code=201, summary="Создать тип помещения")
def create_room_type(payload: RoomTypeCreate, session: DbSession, user: WriteUser):
    return RoomTypeOut.model_validate(service.create_room_type(session, payload.model_dump()))


@router.patch("/{room_type_id}", summary="Изменить тип помещения")
def update_room_type(
    room_type_id: int, payload: RoomTypeUpdate, session: DbSession, user: WriteUser
):
    return RoomTypeOut.model_validate(
        service.update_room_type(session, room_type_id, changed_fields(payload))
    )


@router.delete(
    "/{room_type_id}",
    status_code=204,
    response_class=Response,
    summary="Удалить тип помещения",
)
def delete_room_type(room_type_id: int, session: DbSession, user: WriteUser):
    service.delete_room_type(session, room_type_id)
