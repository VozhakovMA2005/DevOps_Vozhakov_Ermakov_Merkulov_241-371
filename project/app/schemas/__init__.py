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

__all__ = [
    "READ_ONLY_FIELDS",
    "BuildingCreate",
    "BuildingOut",
    "BuildingUpdate",
    "DepartmentCreate",
    "DepartmentOut",
    "DepartmentUpdate",
    "LoginRequest",
    "OrmSchema",
    "Schema",
    "TokenResponse",
    "UserCreate",
    "UserOut",
    "UserUpdate",
    "page_envelope",
]
