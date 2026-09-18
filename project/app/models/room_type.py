"""Тип (целевое назначение) помещения с нормой площади на человека.

Норма — основа правила D5: нормативная вместимость помещения равна рабочей
площади, делённой на норму, с округлением вниз.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RoomType(TimestampMixin, Base):
    __tablename__ = "room_type"
    __table_args__ = (
        UniqueConstraint("code", name="uq_room_type_code"),
        CheckConstraint(
            "area_norm IS NULL OR area_norm > 0", name="ck_room_type_norm_positive"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    #: м² на одного человека. NULL — норма не установлена, правило D5 не считается
    area_norm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    #: Учебный ли это тип: только такие участвуют в матрице допустимости (D1)
    is_teaching: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(300))

    def normative_capacity(self, area: Decimal) -> int | None:
        """Правило D5: сколько человек допускает норма при такой площади."""
        if self.area_norm is None or self.area_norm <= 0:
            return None
        return int(area // self.area_norm)
