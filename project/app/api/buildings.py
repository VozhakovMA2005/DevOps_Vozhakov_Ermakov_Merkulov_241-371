"""Корпуса университета и навигация по этажам."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.deps import CurrentUser, DbSession, WriteUser, page_params
from app.models import Building
from app.schemas import BuildingCreate, BuildingOut, BuildingUpdate, page_envelope
from app.services import buildings as service
from app.services.common import changed_fields, get_or_404
from app.services.paging import paginate

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/buildings", tags=["корпуса"])


@router.get("", summary="Список корпусов")
def list_buildings(
    session: DbSession,
    user: CurrentUser,
    pagination: Pagination,
    q: str | None = Query(default=None, max_length=100),
):
    page, page_size = pagination
    rows, total = paginate(session, service.query_buildings(q), page, page_size)
    return page_envelope([BuildingOut.model_validate(r) for r in rows], total, page, page_size)


@router.post("", status_code=201, summary="Создать корпус")
def create_building(payload: BuildingCreate, session: DbSession, user: WriteUser):
    return BuildingOut.model_validate(service.create_building(session, payload.model_dump()))


@router.get("/{building_id}", summary="Корпус")
def read_building(building_id: int, session: DbSession, user: CurrentUser):
    return BuildingOut.model_validate(get_or_404(session, Building, building_id))


@router.patch("/{building_id}", summary="Изменить корпус")
def update_building(
    building_id: int, payload: BuildingUpdate, session: DbSession, user: WriteUser
):
    return BuildingOut.model_validate(
        service.update_building(session, building_id, changed_fields(payload))
    )


@router.delete(
    "/{building_id}", status_code=204, response_class=Response, summary="Удалить корпус"
)
def delete_building(building_id: int, session: DbSession, user: WriteUser):
    service.delete_building(session, building_id)
