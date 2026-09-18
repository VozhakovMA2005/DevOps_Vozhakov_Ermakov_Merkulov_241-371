"""Схемы входа и текущего пользователя."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, SecretStr

from app.models.user import Role
from app.schemas.common import OrmSchema, Schema


class LoginRequest(Schema):
    username: str = Field(min_length=3, max_length=50)
    #: SecretStr: значение не попадёт ни в repr, ни в журнал
    password: SecretStr = Field(min_length=1)


class TokenResponse(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(OrmSchema):
    id: int
    username: str
    full_name: str
    role: Role
    role_title: str = ""
    is_active: bool
    last_login_at: datetime | None = None


class UserCreate(Schema):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(min_length=1, max_length=150)
    password: SecretStr = Field(min_length=8)
    role: Role


class UserUpdate(Schema):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    password: SecretStr | None = Field(default=None, min_length=8)
    role: Role | None = None
    is_active: bool | None = None
