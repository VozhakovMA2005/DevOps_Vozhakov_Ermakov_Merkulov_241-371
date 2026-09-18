"""История обмеров помещения — ТЗ 4.1.1 и 4.1.5.

Каждая запись фиксирует площадь и вместимость на дату обмера, кто его внёс и
откуда пришли данные. История не переписывается: исправление — это новый обмер.
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import AppUser


class MeasurementSource(enum.StrEnum):
    MANUAL = "MANUAL"  # внесено через веб-интерфейс или API
    IMPORT = "IMPORT"  # загружено из XLSX (этап 3)
    INITIAL = "INITIAL"  # значения при заведении карточки помещения


class RoomMeasurement(TimestampMixin, Base):
    __tablename__ = "room_measurement"
    __table_args__ = (
        CheckConstraint("area > 0", name="ck_measurement_area_positive"),
        CheckConstraint("seats >= 0", name="ck_measurement_seats"),
        CheckConstraint("staff_seats >= 0", name="ck_measurement_staff_seats"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("room.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    area: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: Кто внёс. Запись остаётся, даже если пользователя потом заблокируют
    measured_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT")
    )
    source: Mapped[MeasurementSource] = mapped_column(
        Enum(MeasurementSource, name="measurement_source", native_enum=True),
        nullable=False,
        default=MeasurementSource.MANUAL,
    )
    note: Mapped[str | None] = mapped_column(String(300))

    measured_by: Mapped[AppUser | None] = relationship(lazy="joined")
