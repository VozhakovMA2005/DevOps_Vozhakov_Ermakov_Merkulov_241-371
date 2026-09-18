"""Подбор аудитории под занятие — правила D1, D2, D6."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.schemas import SuitableRoomOut
from app.services import selection as selection_service

router = APIRouter(prefix="/api/v1/rooms", tags=["подбор аудитории"])


@router.get("/suitable", summary="Подбор аудитории под занятие (D1, D2, D6)")
def suitable(
    session: DbSession,
    user: CurrentUser,
    discipline_id: int,
    group_size: int = Query(ge=1, le=10000),
    building_id: int | None = None,
    allow_overload: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
):
    result = selection_service.suitable_rooms(
        session,
        discipline_id=discipline_id,
        group_size=group_size,
        building_id=building_id,
        allow_overload=allow_overload,
        limit=limit,
    )
    result["items"] = [SuitableRoomOut.model_validate(item) for item in result["items"]]
    return result
