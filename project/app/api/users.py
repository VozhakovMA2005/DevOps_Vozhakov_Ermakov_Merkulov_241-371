"""Управление учётными записями — только администратор системы (ТЗ 3.3)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DbSession, SysAdmin
from app.models import ROLE_TITLES, AppUser
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services import auth as service
from app.services.common import changed_fields, get_or_404

router = APIRouter(prefix="/api/v1/users", tags=["пользователи"])


def _out(user: AppUser) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        role_title=ROLE_TITLES[user.role],
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


@router.get("", summary="Список учётных записей")
def list_users(session: DbSession, admin: SysAdmin) -> list[UserOut]:
    rows = session.scalars(select(AppUser).order_by(AppUser.username)).all()
    return [_out(row) for row in rows]


@router.post("", status_code=201, summary="Создать учётную запись")
def create_user(payload: UserCreate, session: DbSession, admin: SysAdmin) -> UserOut:
    user = service.create_user(session, payload.model_dump())
    return _out(user)


@router.get("/{user_id}", summary="Учётная запись")
def read_user(user_id: int, session: DbSession, admin: SysAdmin) -> UserOut:
    return _out(get_or_404(session, AppUser, user_id))


@router.patch("/{user_id}", summary="Изменить учётную запись")
def update_user(
    user_id: int, payload: UserUpdate, session: DbSession, admin: SysAdmin
) -> UserOut:
    user = service.update_user(session, user_id, changed_fields(payload), admin)
    return _out(user)
