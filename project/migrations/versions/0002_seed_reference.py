"""Начальные справочные данные: типы помещений

Revision ID: 0002_seed_reference
Revises: 0001_initial
Создана: 2026-09-18

Без справочника типов нельзя завести ни одного помещения: тип обязателен и
несёт норму площади на человека, от которой считается правило D5. Поэтому
начальные значения приезжают миграцией, а не руками после развёртывания.

Нормы взяты как рабочие значения проекта и правятся через справочник.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_seed_reference"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

ROOM_TYPES = (
    ("LECTURE", "Лекционная аудитория", "2.50", True, "Поточные занятия"),
    ("SEMINAR", "Семинарская аудитория", "2.50", True, "Практические и семинары"),
    ("LAB", "Лаборатория", "4.50", True, "Рабочее место с оборудованием"),
    ("COMPUTER", "Компьютерный класс", "6.00", True, "Норма на рабочее место с ПК"),
    ("SPORT", "Спортивный зал", "4.00", True, "Занятия физической культурой"),
    ("OFFICE", "Служебное помещение", None, False, "Кабинеты сотрудников"),
    ("UTILITY", "Вспомогательное помещение", None, False, "Склады, коридоры, санузлы"),
)


def upgrade() -> None:
    room_type = sa.table(
        "room_type",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("area_norm", sa.Numeric),
        sa.column("is_teaching", sa.Boolean),
        sa.column("note", sa.String),
    )
    op.bulk_insert(
        room_type,
        [
            {
                "code": code,
                "name": name,
                "area_norm": norm,
                "is_teaching": teaching,
                "note": note,
            }
            for code, name, norm, teaching, note in ROOM_TYPES
        ],
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, *_ in ROOM_TYPES)
    op.execute(f"DELETE FROM room_type WHERE code IN ({codes})")
