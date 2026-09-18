"""Подразделения университета и их иерархия."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.deps import CurrentUser, DbSession, WriteUser, page_params
from app.models import Department
from app.schemas import DepartmentCreate, DepartmentOut, DepartmentUpdate, page_envelope
from app.services import departments as service
from app.services.common import changed_fields, get_or_404
from app.services.paging import paginate

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/departments", tags=["подразделения"])


@router.get("", summary="Список подразделений")
def list_departments(
    session: DbSession,
    user: CurrentUser,
    pagination: Pagination,
    parent_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
):
    page, page_size = pagination
    rows, total = paginate(session, service.query_departments(parent_id, q), page, page_size)
    return page_envelope(
        [DepartmentOut.model_validate(r) for r in rows], total, page, page_size
    )


@router.post("", status_code=201, summary="Создать подразделение")
def create_department(payload: DepartmentCreate, session: DbSession, user: WriteUser):
    return DepartmentOut.model_validate(
        service.create_department(session, payload.model_dump())
    )


@router.get("/{department_id}", summary="Подразделение")
def read_department(department_id: int, session: DbSession, user: CurrentUser):
    return DepartmentOut.model_validate(get_or_404(session, Department, department_id))


@router.patch("/{department_id}", summary="Изменить подразделение")
def update_department(
    department_id: int, payload: DepartmentUpdate, session: DbSession, user: WriteUser
):
    return DepartmentOut.model_validate(
        service.update_department(session, department_id, changed_fields(payload))
    )


@router.delete(
    "/{department_id}",
    status_code=204,
    response_class=Response,
    summary="Удалить подразделение",
)
def delete_department(department_id: int, session: DbSession, user: WriteUser):
    service.delete_department(session, department_id)
