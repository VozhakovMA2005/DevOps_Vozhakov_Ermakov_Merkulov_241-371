"""Помещение — центральная сущность аудиторного фонда (ТЗ 4.1.5)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.building import Building
from app.models.room_type import RoomType


class Room(TimestampMixin, Base):
    __tablename__ = "room"
    __table_args__ = (
        UniqueConstraint("building_id", "number", name="uq_room_building_number"),
        CheckConstraint("area > 0", name="ck_room_area_positive"),
        CheckConstraint("seats >= 0", name="ck_room_seats_non_negative"),
        CheckConstraint("staff_seats >= 0", name="ck_room_staff_seats_non_negative"),
        CheckConstraint("floor <> 0", name="ck_room_floor_not_zero"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    building_id: Mapped[int] = mapped_column(
        ForeignKey("building.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    floor: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_type.id", ondelete="RESTRICT"), nullable=False
    )
    #: Помещение может быть закреплено за подразделением (ТЗ 4.1.5)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="RESTRICT")
    )
    #: Рабочая площадь, м². Меняется через обмер, а не правкой поля напрямую
    area: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staff_seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: ОБЪЁМ (ВМЕСТИМОСТЬ) ПОМЕЩЕНИЯ — всего людей.
    #: Считает база, приложение это значение не принимает и не пишет (ТЗ 4.1.1:
    #: «автоматическое вычисление суммарного объема на стороне базы данных»)
    volume: Mapped[int] = mapped_column(
        Integer, Computed("seats + staff_seats", persisted=True)
    )

    #: Правило D6: непригодное помещение не участвует в подборе
    is_usable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(500))

    building: Mapped[Building] = relationship(lazy="joined")
    room_type: Mapped[RoomType] = relationship(lazy="joined")

    def normative_capacity(self) -> int | None:
        """Правило D5 для текущей площади и типа помещения."""
        return self.room_type.normative_capacity(self.area)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Room {self.number} {self.area} м²>"
