"""Подразделения университета: иерархия и правила её целостности."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.errors import DepartmentCycle, HasDependents
from app.models import Department, Room
from app.services.common import get_or_404, get_related_or_409
from app.services.paging import commit


def check_no_cycle(session: Session, department_id: int, parent_id: int | None) -> None:
    """Иерархия подразделений — дерево. CHECK в схеме ловит только parent_id = id."""
    seen = {department_id}
    current = parent_id
    while current is not None:
        if current in seen:
            raise DepartmentCycle(
                "Такое родительское подразделение образует цикл в иерархии",
                details={"department_id": department_id, "parent_id": parent_id},
            )
        seen.add(current)
        current = session.scalar(select(Department.parent_id).where(Department.id == current))


def create_department(session: Session, payload: dict[str, Any]) -> Department:
    if payload.get("parent_id") is not None:
        get_related_or_409(session, Department, payload["parent_id"], "parent_id")
    department = Department(**payload)
    session.add(department)
    commit(session)
    return department


def update_department(
    session: Session, department_id: int, changes: dict[str, Any]
) -> Department:
    department = get_or_404(session, Department, department_id)
    if "parent_id" in changes:
        if changes["parent_id"] is not None:
            get_related_or_409(session, Department, changes["parent_id"], "parent_id")
        check_no_cycle(session, department_id, changes["parent_id"])
    for field, value in changes.items():
        setattr(department, field, value)
    commit(session)
    return department


def delete_department(session: Session, department_id: int) -> None:
    department = get_or_404(session, Department, department_id)
    children = session.scalar(
        select(func.count())
        .select_from(Department)
        .where(Department.parent_id == department_id)
    )
    if children:
        raise HasDependents(
            f"У подразделения {department.code} есть дочерние ({children})",
            details={"department_id": department_id, "children_count": int(children)},
        )
    rooms = session.scalar(
        select(func.count()).select_from(Room).where(Room.department_id == department_id)
    )
    if rooms:
        raise HasDependents(
            f"За подразделением {department.code} закреплены помещения ({rooms})",
            details={"department_id": department_id, "rooms_count": int(rooms)},
        )
    session.delete(department)
    commit(session)


def query_departments(parent_id: int | None, q: str | None) -> Select:
    statement = select(Department).order_by(Department.code)
    if parent_id is not None:
        statement = statement.where(Department.parent_id == parent_id)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Department.name).like(pattern),
                func.lower(Department.code).like(pattern),
            )
        )
    return statement
