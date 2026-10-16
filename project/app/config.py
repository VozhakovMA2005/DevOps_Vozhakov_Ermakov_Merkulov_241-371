"""Конфигурация приложения — только из переменных окружения.

ТЗ 4.6: конфигурационные параметры, ключи доступа и пароли СУБД передаются
исключительно через переменные окружения. Ключ подписи токенов обязателен —
без него приложение не запускается.

Значения читаются один раз на старте. Это осознанно: приложение либо
поднимается с корректной конфигурацией, либо не поднимается вовсе, а не падает
через час на первом обращении к незаданной переменной.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

APP_ENVS = ("development", "test", "production")
LOG_FORMATS = ("json", "text")
#: Заглушка из .env.example: с ней в продуктивной среде стартовать нельзя
PLACEHOLDER_SECRETS = {
    "CHANGE_ME",
    "CHANGE_ME_СГЕНЕРИРУЙТЕ_СВОЙ_КЛЮЧ",
    "changeme",
    "secret",
}


class ConfigError(RuntimeError):
    """Конфигурация не годится для запуска. Сообщение читает человек."""


@dataclass(frozen=True, slots=True)
class Config:
    app_env: str
    app_host: str
    app_port: int
    database_url: str
    jwt_secret: str
    jwt_ttl_minutes: int
    login_max_attempts: int
    login_lock_minutes: int
    log_level: str
    log_format: str
    page_size_default: int
    page_size_max: int
    max_upload_bytes: int
    cookie_secure: bool
    git_commit: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(f"{name} должно быть true или false, получено: {raw!r}")


def _int(name: str, default: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.getenv(name, default)
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} должно быть целым числом, получено: {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} должно быть не меньше {minimum}, получено: {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} должно быть не больше {maximum}, получено: {value}")
    return value


def load_config() -> Config:
    """Собирает конфигурацию и отклоняет неверные значения с понятным текстом."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env not in APP_ENVS:
        raise ConfigError(
            f"APP_ENV должно быть одним из {', '.join(APP_ENVS)}, получено: {app_env!r}"
        )

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise ConfigError(
            "Не задана обязательная переменная DATABASE_URL. "
            "Скопируйте .env.example в .env и подставьте адрес базы."
        )
    if not database_url.startswith("postgresql"):
        raise ConfigError(
            "DATABASE_URL должна указывать на PostgreSQL "
            f"(ожидается postgresql+psycopg://…), получено: {database_url.split(':', 1)[0]!r}"
        )

    jwt_secret = os.getenv("JWT_SECRET", "").strip()
    if not jwt_secret:
        raise ConfigError(
            "Не задана обязательная переменная JWT_SECRET — ключ подписи токенов "
            "(ТЗ 4.6). Сгенерировать: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    if app_env == "production" and (jwt_secret in PLACEHOLDER_SECRETS or len(jwt_secret) < 32):
        raise ConfigError(
            "JWT_SECRET в продуктивной среде не должен быть значением из примера "
            "и должен быть не короче 32 символов"
        )

    log_format = os.getenv("LOG_FORMAT", "json").strip().lower()
    if log_format not in LOG_FORMATS:
        raise ConfigError(f"LOG_FORMAT должно быть json или text, получено: {log_format!r}")

    page_size_default = _int("PAGE_SIZE_DEFAULT", "50")
    page_size_max = _int("PAGE_SIZE_MAX", "200")
    if page_size_default > page_size_max:
        raise ConfigError(
            f"PAGE_SIZE_DEFAULT ({page_size_default}) больше PAGE_SIZE_MAX ({page_size_max})"
        )

    return Config(
        app_env=app_env,
        # По умолчанию слушаем только локальный адрес. Открывать все
        # интерфейсы — осознанное решение среды развёртывания, а не значение
        # по умолчанию: в docker-compose и в audfond.env APP_HOST задан явно.
        # Так же уходит замечание bandit B104, и подавлять его не нужно
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=_int("APP_PORT", "8000", minimum=1, maximum=65535),
        database_url=database_url,
        jwt_secret=jwt_secret,
        jwt_ttl_minutes=_int("JWT_TTL_MINUTES", "60"),
        login_max_attempts=_int("LOGIN_MAX_ATTEMPTS", "5"),
        login_lock_minutes=_int("LOGIN_LOCK_MINUTES", "15"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        log_format=log_format,
        page_size_default=page_size_default,
        page_size_max=page_size_max,
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", "20971520"),
        # Флаг Secure у cookie с токеном. По умолчанию включён в продуктивной
        # среде, но вынесен в отдельную настройку: браузер НЕ сохраняет
        # Secure-cookie, полученную по http. Пока перед приложением нет TLS,
        # на стенде ставится COOKIE_SECURE=false, иначе вход молча не
        # срабатывает — страница возвращает на форму.
        cookie_secure=_bool("COOKIE_SECURE", app_env == "production"),
        git_commit=os.getenv("GIT_COMMIT", "unknown").strip() or "unknown",
    )
