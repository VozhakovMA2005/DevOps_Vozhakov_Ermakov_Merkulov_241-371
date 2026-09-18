"""Дисциплины и матрица допустимости «дисциплина — тип помещения» (D1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.deps import CurrentUser, DbSession, WriteUser, page_params
from app.models import Discipline
from app.schemas import DisciplineCreate, DisciplineOut, DisciplineUpdate, page_envelope
from app.services import disciplines as service
from app.services.common import changed_fields, get_or_404
from app.services.paging import paginate

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/disciplines", tags=["дисциплины"])


@router.get("", summary="Список дисциплин с матрицей допустимости")
def list_disciplines(
    session: DbSession,
    user: CurrentUser,
    pagination: Pagination,
    q: str | None = Query(default=None, max_length=100),
):
    page, page_size = pagination
    rows, total = paginate(session, service.query_disciplines(q), page, page_size)
    return page_envelope(
        [DisciplineOut.model_validate(r) for r in rows], total, page, page_size
    )


@router.post("", status_code=201, summary="Создать дисциплину")
def create_discipline(payload: DisciplineCreate, session: DbSession, user: WriteUser):
    return DisciplineOut.model_validate(
        service.create_discipline(session, payload.model_dump())
    )


@router.get("/{discipline_id}", summary="Дисциплина")
def read_discipline(discipline_id: int, session: DbSession, user: CurrentUser):
    return DisciplineOut.model_validate(get_or_404(session, Discipline, discipline_id))


@router.patch("/{discipline_id}", summary="Изменить дисциплину и матрицу")
def update_discipline(
    discipline_id: int, payload: DisciplineUpdate, session: DbSession, user: WriteUser
):
    return DisciplineOut.model_validate(
        service.update_discipline(session, discipline_id, changed_fields(payload))
    )


@router.delete(
    "/{discipline_id}", status_code=204, response_class=Response, summary="Удалить дисциплину"
)
def delete_discipline(discipline_id: int, session: DbSession, user: WriteUser):
    service.delete_discipline(session, discipline_id)
