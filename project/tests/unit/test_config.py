"""Разбор конфигурации. Базы для этих проверок не нужно."""

from __future__ import annotations

import pytest

from app.config import ConfigError, load_config

GOOD_DB = "postgresql+psycopg://audfond:pass@localhost:5432/audfond"
GOOD_SECRET = "ключ-подписи-достаточной-длины-1234567890"


def _env(monkeypatch, **overrides) -> None:
    for name in [
        *overrides,
        "APP_ENV",
        "DATABASE_URL",
        "JWT_SECRET",
        "LOG_FORMAT",
        "PAGE_SIZE_DEFAULT",
        "PAGE_SIZE_MAX",
        "APP_PORT",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", GOOD_DB)
    monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


def test_defaults(monkeypatch):
    _env(monkeypatch)
    config = load_config()
    assert config.app_env == "development"
    assert config.page_size_default == 50
    assert config.login_max_attempts == 5
    assert config.is_production is False


def test_database_url_is_required(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_config()


def test_jwt_secret_is_required(monkeypatch):
    """ТЗ 4.6: без ключа подписи приложение не запускается."""
    _env(monkeypatch)
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_config()


def test_placeholder_secret_rejected_in_production(monkeypatch):
    _env(monkeypatch, APP_ENV="production", JWT_SECRET="CHANGE_ME")
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_config()


def test_placeholder_secret_allowed_in_development(monkeypatch):
    _env(monkeypatch, JWT_SECRET="CHANGE_ME")
    assert load_config().jwt_secret == "CHANGE_ME"


def test_non_postgres_url_rejected(monkeypatch):
    _env(monkeypatch, DATABASE_URL="sqlite:///audfond.db")
    with pytest.raises(ConfigError, match="PostgreSQL"):
        load_config()


def test_unknown_env_rejected(monkeypatch):
    _env(monkeypatch, APP_ENV="staging")
    with pytest.raises(ConfigError, match="APP_ENV"):
        load_config()


def test_page_size_default_above_max(monkeypatch):
    _env(monkeypatch, PAGE_SIZE_DEFAULT="500", PAGE_SIZE_MAX="200")
    with pytest.raises(ConfigError, match="PAGE_SIZE_DEFAULT"):
        load_config()


def test_non_numeric_port(monkeypatch):
    _env(monkeypatch, APP_PORT="восемь")
    with pytest.raises(ConfigError, match="APP_PORT"):
        load_config()


def test_cookie_secure_follows_app_env_by_default(monkeypatch):
    """Без явной настройки Secure включается только в продуктивной среде."""
    _env(monkeypatch, APP_ENV="production", JWT_SECRET=GOOD_SECRET)
    assert load_config().cookie_secure is True

    _env(monkeypatch, APP_ENV="development")
    assert load_config().cookie_secure is False


def test_cookie_secure_can_be_switched_off_in_production(monkeypatch):
    """Стенд без TLS: браузер не сохранит Secure-cookie, пришедшую по http."""
    _env(monkeypatch, APP_ENV="production", JWT_SECRET=GOOD_SECRET, COOKIE_SECURE="false")
    assert load_config().cookie_secure is False


def test_cookie_secure_accepts_usual_spellings(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        _env(monkeypatch, COOKIE_SECURE=value)
        assert load_config().cookie_secure is True, value
    for value in ("0", "false", "FALSE", "no", "off"):
        _env(monkeypatch, COOKIE_SECURE=value)
        assert load_config().cookie_secure is False, value


def test_cookie_secure_rejects_nonsense(monkeypatch):
    _env(monkeypatch, COOKIE_SECURE="может-быть")
    with pytest.raises(ConfigError, match="COOKIE_SECURE"):
        load_config()
