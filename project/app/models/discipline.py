"""Дисциплина и матрица допустимости «дисциплина — тип помещения».

Матрица — основа правила D1: занятие по дисциплине может быть назначено только
в помещение разрешённого для неё типа.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.room_type import RoomType

#: Матрица допустимости: связь «многие ко многим» (ТЗ 4.1.5)
discipline_room_type = Table(
    "discipline_room_type",
    Base.metadata,
    Column(
        "discipline_id",
        ForeignKey("discipline.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "room_type_id",
        ForeignKey("room_type.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Discipline(TimestampMixin, Base):
    __tablename__ = "discipline"
    __table_args__ = (UniqueConstraint("code", name="uq_discipline_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))

    #: Типы помещений, в которых дисциплину разрешено проводить
    allowed_room_types: Mapped[list[RoomType]] = relationship(
        secondary=discipline_room_type, lazy="selectin", order_by="RoomType.code"
    )

    def allows(self, room_type_id: int) -> bool:
        """Правило D1 для одного типа помещения."""
        return any(item.id == room_type_id for item in self.allowed_room_types)
