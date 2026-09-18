"""Подразделение университета: институт, факультет, кафедра — ТЗ 4.1.5."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Department(TimestampMixin, Base):
    __tablename__ = "department"
    __table_args__ = (
        UniqueConstraint("code", name="uq_department_code"),
        # Прямое самородительство ловит база; длинные циклы — приложение
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_department_not_self_parent"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="RESTRICT")
    )
    head_fio: Mapped[str | None] = mapped_column(String(150))

    parent: Mapped[Department | None] = relationship(remote_side="Department.id")
