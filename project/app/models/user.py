"""Учётная запись и роль — ТЗ 3.3.

Таблица называется app_user: user — зарезервированное слово PostgreSQL.
Пароль хранится только как хэш Argon2 с индивидуальной солью (ТЗ 4.1.1).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Role(enum.StrEnum):
    """Роли из подраздела 3.3 ТЗ."""

    SYS_ADMIN = "SYS_ADMIN"  # администратор системы
    FUND_ADMIN = "FUND_ADMIN"  # администратор аудиторного фонда
    DISPATCHER = "DISPATCHER"  # диспетчер расписания
    OBSERVER = "OBSERVER"  # наблюдатель
    SERVICE = "SERVICE"  # внешняя информационная система

    @property
    def label(self) -> str:
        """Название роли по-русски. Не title: у str это уже занятый метод."""
        return ROLE_TITLES[self]


ROLE_TITLES = {
    Role.SYS_ADMIN: "Администратор системы",
    Role.FUND_ADMIN: "Администратор аудиторного фонда",
    Role.DISPATCHER: "Диспетчер расписания",
    Role.OBSERVER: "Наблюдатель",
    Role.SERVICE: "Внешняя информационная система",
}

#: Кто имеет право менять данные. Наблюдатель и внешняя система — только чтение.
WRITE_ROLES = (Role.SYS_ADMIN, Role.FUND_ADMIN, Role.DISPATCHER)


class AppUser(TimestampMixin, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("username", name="uq_app_user_username"),
        CheckConstraint("char_length(username) >= 3", name="ck_app_user_username_len"),
        CheckConstraint("failed_attempts >= 0", name="ck_app_user_attempts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    #: Argon2, соль внутри строки хэша. Пароль в открытом виде не хранится нигде
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", native_enum=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Счётчик неудачных попыток входа подряд — ТЗ 4.1.1
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppUser {self.username} {self.role.value}>"
