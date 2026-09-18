"""Корпус университета — ТЗ 4.1.5."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Building(TimestampMixin, Base):
    __tablename__ = "building"
    __table_args__ = (
        UniqueConstraint("code", name="uq_building_code"),
        CheckConstraint("floors_count BETWEEN 1 AND 100", name="ck_building_floors"),
        CheckConstraint(
            "passport_area IS NULL OR passport_area > 0", name="ck_building_area_positive"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    floors_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    has_basement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Паспортная площадь здания, м² (ТЗ 4.1.1)
    passport_area: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    def floor_allowed(self, floor: int) -> bool:
        """Этаж 0 не используется, −1 — только при наличии подвала."""
        if floor == 0:
            return False
        if floor < 0:
            return self.has_basement and floor == -1
        return floor <= self.floors_count

    def floors_hint(self) -> str:
        low = "−1 (подвал), " if self.has_basement else ""
        return f"{low}1…{self.floors_count}"
