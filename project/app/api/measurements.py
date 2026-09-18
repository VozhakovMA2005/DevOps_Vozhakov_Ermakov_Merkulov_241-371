"""История обмеров помещения."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUser, DbSession, WriteUser
from app.models import Room
from app.schemas import MeasurementCreate, MeasurementOut
from app.services import measurements as measurement_service
from app.services.common import get_or_404

router = APIRouter(prefix="/api/v1/rooms", tags=["обмеры"])


@router.get("/{room_id}/measurements", summary="История обмеров помещения")
def list_measurements(room_id: int, session: DbSession, user: CurrentUser):
    get_or_404(session, Room, room_id)
    rows = session.scalars(measurement_service.query(room_id)).all()
    return [
        MeasurementOut(
            id=row.id,
            room_id=row.room_id,
            area=row.area,
            seats=row.seats,
            staff_seats=row.staff_seats,
            measured_on=row.measured_on,
            source=row.source,
            note=row.note,
            measured_by_name=row.measured_by.full_name if row.measured_by else None,
        )
        for row in rows
    ]


@router.post("/{room_id}/measurements", status_code=201, summary="Внести обмер")
def create_measurement(
    room_id: int, payload: MeasurementCreate, session: DbSession, user: WriteUser
):
    row = measurement_service.create(session, room_id, payload.model_dump(), user)
    return MeasurementOut(
        id=row.id,
        room_id=row.room_id,
        area=row.area,
        seats=row.seats,
        staff_seats=row.staff_seats,
        measured_on=row.measured_on,
        source=row.source,
        note=row.note,
        measured_by_name=user.full_name,
    )
