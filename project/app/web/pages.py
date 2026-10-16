"""Веб-интерфейс: страницы каталога аудиторного фонда.

Страницы отрисовываются на сервере (Jinja2 + Bootstrap 5.3, файлы лежат
локально в app/web/static — ТЗ 4.5 запрещает внешние CDN). Изменения данных
идут через то же REST API, что и у смежных систем: одна проверка правил на
всех, а не вторая копия логики в шаблонах.

Не вошедшего пользователя страницы отправляют на форму входа (ТЗ 4.6).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.deps import DbSession, MaybeUser
from app.models import ROLE_TITLES, Building, Department, Discipline, Room, RoomType
from app.services import measurements as measurement_service
from app.services import rooms as rooms_service
from app.services.common import get_or_404

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter(tags=["веб-интерфейс"], include_in_schema=False)


def _login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


def _page(request: Request, user, template: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "role_title": ROLE_TITLES[user.role] if user else "",
            "can_write": bool(user and user.can_write()),
            **context,
        },
    )


@router.get("/login", response_class=HTMLResponse, summary="Форма входа")
def login_page(request: Request, user: MaybeUser, next: str = "/"):
    if user is not None:
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None, "next": next})


@router.get("/", response_class=HTMLResponse, summary="Каталог: корпуса")
def index(request: Request, user: MaybeUser, session: DbSession):
    if user is None:
        return _login_redirect(request)
    buildings = list(session.scalars(select(Building).order_by(Building.code)))
    stats = {
        building.id: rooms_service.floors_of(session, building.id) for building in buildings
    }
    totals = {
        building.id: sum(row["rooms_count"] for row in stats[building.id])
        for building in buildings
    }
    return _page(
        request,
        user,
        "buildings.html",
        buildings=buildings,
        totals=totals,
        crumbs=[("Каталог", None)],
    )


@router.get("/buildings/{building_id}", response_class=HTMLResponse, summary="Этажи корпуса")
def building_page(request: Request, building_id: int, user: MaybeUser, session: DbSession):
    if user is None:
        return _login_redirect(request)
    building = get_or_404(session, Building, building_id)
    floors = rooms_service.floors_of(session, building_id)
    return _page(
        request,
        user,
        "building.html",
        building=building,
        floors=floors,
        crumbs=[("Каталог", "/"), (f"Корпус {building.code}", None)],
    )


@router.get(
    "/buildings/{building_id}/floors/{floor}",
    response_class=HTMLResponse,
    summary="Помещения этажа",
)
def floor_page(
    request: Request, building_id: int, floor: int, user: MaybeUser, session: DbSession
):
    if user is None:
        return _login_redirect(request)
    building = get_or_404(session, Building, building_id)
    rooms = list(session.scalars(rooms_service.query(building_id=building_id, floor=floor)))
    return _page(
        request,
        user,
        "floor.html",
        building=building,
        floor=floor,
        rooms=rooms,
        room_types=list(session.scalars(select(RoomType).order_by(RoomType.code))),
        departments=list(session.scalars(select(Department).order_by(Department.code))),
        crumbs=[
            ("Каталог", "/"),
            (f"Корпус {building.code}", f"/buildings/{building.id}"),
            (f"Этаж {floor}", None),
        ],
    )


@router.get("/rooms/{room_id}", response_class=HTMLResponse, summary="Карточка помещения")
def room_page(request: Request, room_id: int, user: MaybeUser, session: DbSession):
    if user is None:
        return _login_redirect(request)
    room = get_or_404(session, Room, room_id)
    history = list(session.scalars(measurement_service.query(room_id)))
    department = session.get(Department, room.department_id) if room.department_id else None
    return _page(
        request,
        user,
        "room.html",
        room=room,
        history=history,
        department=department,
        capacity=room.normative_capacity(),
        crumbs=[
            ("Каталог", "/"),
            (f"Корпус {room.building.code}", f"/buildings/{room.building_id}"),
            (f"Этаж {room.floor}", f"/buildings/{room.building_id}/floors/{room.floor}"),
            (f"Помещение {room.number}", None),
        ],
    )


@router.get("/disciplines", response_class=HTMLResponse, summary="Матрица допустимости")
def disciplines_page(request: Request, user: MaybeUser, session: DbSession):
    if user is None:
        return _login_redirect(request)
    return _page(
        request,
        user,
        "disciplines.html",
        disciplines=list(session.scalars(select(Discipline).order_by(Discipline.code))),
        room_types=list(session.scalars(select(RoomType).order_by(RoomType.code))),
        crumbs=[("Дисциплины и матрица допустимости", None)],
    )


@router.get("/selection", response_class=HTMLResponse, summary="Подбор аудитории")
def selection_page(request: Request, user: MaybeUser, session: DbSession):
    if user is None:
        return _login_redirect(request)
    return _page(
        request,
        user,
        "selection.html",
        disciplines=list(session.scalars(select(Discipline).order_by(Discipline.code))),
        buildings=list(session.scalars(select(Building).order_by(Building.code))),
        crumbs=[("Подбор аудитории", None)],
    )
