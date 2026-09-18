"""Демонстрационные данные для показа и ручной проверки.

Только обезличенные значения: ФИО и учебные группы не используются
(ТЗ 4.6, Федеральный закон № 152-ФЗ). Повторный запуск ничего не дублирует.

    python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import load_config
from app.db import init_engine, session_factory
from app.models import (
    AppUser,
    Building,
    Department,
    Discipline,
    MeasurementSource,
    Role,
    Room,
    RoomMeasurement,
    RoomType,
)
from app.security import hash_password

USERS = [
    ("fund", "Инженер аудиторного фонда", Role.FUND_ADMIN),
    ("dispatcher", "Диспетчер расписания", Role.DISPATCHER),
    ("observer", "Наблюдатель", Role.OBSERVER),
]

BUILDINGS = [
    ("A", "Главный корпус", "ул. Большая Семёновская, 38", 6, True, "9800.00"),
    ("B", "Лабораторный корпус", "ул. Павла Корчагина, 22", 4, False, "5400.00"),
]

DEPARTMENTS = [
    ("FIT", "Факультет информационных технологий", None),
    ("KAF-IB", "Кафедра информационной безопасности", "FIT"),
    ("KAF-VT", "Кафедра вычислительной техники", "FIT"),
    ("UMU", "Учебно-методическое управление", None),
]

#: код корпуса, номер, этаж, тип, площадь, мест, мест сотрудникам, подразделение, пригодно
ROOMS = [
    ("A", "101", 1, "LECTURE", "180.00", 70, 1, "FIT", True),
    ("A", "102", 1, "LECTURE", "150.00", 58, 1, "FIT", True),
    ("A", "201", 2, "SEMINAR", "62.50", 24, 1, "KAF-IB", True),
    ("A", "202", 2, "SEMINAR", "58.00", 22, 1, "KAF-IB", True),
    ("A", "203", 2, "COMPUTER", "96.00", 15, 1, "KAF-IB", True),
    ("A", "301", 3, "LAB", "108.00", 23, 1, "KAF-VT", True),
    ("A", "302", 3, "LAB", "90.00", 19, 1, "KAF-VT", False),
    ("A", "401", 4, "OFFICE", "34.00", 0, 4, "UMU", True),
    ("A", "-101", -1, "UTILITY", "40.00", 0, 0, None, True),
    ("B", "105", 1, "COMPUTER", "120.00", 19, 1, "KAF-VT", True),
    ("B", "106", 1, "COMPUTER", "78.00", 12, 1, "KAF-VT", True),
    ("B", "201", 2, "LAB", "135.00", 29, 1, "KAF-IB", True),
    ("B", "202", 2, "SEMINAR", "45.00", 17, 1, "KAF-IB", True),
    ("B", "301", 3, "SPORT", "288.00", 70, 2, None, True),
]

DISCIPLINES = [
    ("IB-01", "Основы информационной безопасности", ["LECTURE", "SEMINAR"]),
    ("IB-02", "Криптографические методы защиты", ["SEMINAR", "COMPUTER"]),
    ("VT-01", "Схемотехника", ["LAB"]),
    ("VT-02", "Программирование", ["COMPUTER", "SEMINAR"]),
    ("FK-01", "Физическая культура", ["SPORT"]),
]


def main() -> int:
    config = load_config()
    init_engine(config.database_url)

    with session_factory()() as session:
        types = {row.code: row for row in session.scalars(select(RoomType))}
        if not types:
            print("Справочник типов помещений пуст: сначала накатите миграции")
            return 1

        for username, full_name, role in USERS:
            if session.scalar(select(AppUser).where(AppUser.username == username)) is None:
                session.add(
                    AppUser(
                        username=username,
                        full_name=full_name,
                        password_hash=hash_password("demo-пароль-2026"),
                        role=role,
                    )
                )

        departments: dict[str, Department] = {}
        for code, name, _parent in DEPARTMENTS:
            row = session.scalar(select(Department).where(Department.code == code))
            if row is None:
                row = Department(code=code, name=name)
                session.add(row)
            departments[code] = row
        session.flush()
        for code, _name, parent_code in DEPARTMENTS:
            if parent_code:
                departments[code].parent_id = departments[parent_code].id

        buildings: dict[str, Building] = {}
        for code, name, address, floors, basement, area in BUILDINGS:
            row = session.scalar(select(Building).where(Building.code == code))
            if row is None:
                row = Building(
                    code=code,
                    name=name,
                    address=address,
                    floors_count=floors,
                    has_basement=basement,
                    passport_area=Decimal(area),
                )
                session.add(row)
            buildings[code] = row
        session.flush()

        created = 0
        for b_code, number, floor, type_code, area, seats, staff, dept, usable in ROOMS:
            building = buildings[b_code]
            exists = session.scalar(
                select(Room).where(Room.building_id == building.id, Room.number == number)
            )
            if exists is not None:
                continue
            room = Room(
                building_id=building.id,
                number=number,
                floor=floor,
                room_type_id=types[type_code].id,
                department_id=departments[dept].id if dept else None,
                area=Decimal(area),
                seats=seats,
                staff_seats=staff,
                is_usable=usable,
            )
            session.add(room)
            session.flush()
            session.add(
                RoomMeasurement(
                    room_id=room.id,
                    area=room.area,
                    seats=room.seats,
                    staff_seats=room.staff_seats,
                    measured_on=date(2026, 9, 1),
                    source=MeasurementSource.INITIAL,
                    note="Демонстрационные данные",
                )
            )
            created += 1

        for code, name, allowed in DISCIPLINES:
            row = session.scalar(select(Discipline).where(Discipline.code == code))
            if row is None:
                row = Discipline(code=code, name=name)
                session.add(row)
            row.allowed_room_types = [types[t] for t in allowed]

        session.commit()

    print(
        f"Демонстрационные данные готовы: корпусов {len(BUILDINGS)}, "
        f"помещений добавлено {created}, дисциплин {len(DISCIPLINES)}"
    )
    print("Учётные записи показа: fund / dispatcher / observer, пароль demo-пароль-2026")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
