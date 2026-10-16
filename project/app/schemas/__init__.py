"""Схемы Pydantic: то, что приложение принимает и отдаёт по HTTP."""

from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.building import BuildingCreate, BuildingOut, BuildingUpdate
from app.schemas.common import READ_ONLY_FIELDS, OrmSchema, Schema, page_envelope
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.schemas.discipline import DisciplineCreate, DisciplineOut, DisciplineUpdate
from app.schemas.measurement import MeasurementCreate, MeasurementOut
from app.schemas.room import RoomCreate, RoomOut, RoomUpdate
from app.schemas.room_type import RoomTypeCreate, RoomTypeOut, RoomTypeUpdate
from app.schemas.selection import SuitableRoomOut

__all__ = [
    "READ_ONLY_FIELDS",
    "BuildingCreate",
    "BuildingOut",
    "BuildingUpdate",
    "DepartmentCreate",
    "DepartmentOut",
    "DepartmentUpdate",
    "DisciplineCreate",
    "DisciplineOut",
    "DisciplineUpdate",
    "LoginRequest",
    "MeasurementCreate",
    "MeasurementOut",
    "OrmSchema",
    "RoomCreate",
    "RoomOut",
    "RoomTypeCreate",
    "RoomTypeOut",
    "RoomTypeUpdate",
    "RoomUpdate",
    "Schema",
    "SuitableRoomOut",
    "TokenResponse",
    "UserCreate",
    "UserOut",
    "UserUpdate",
    "page_envelope",
]
