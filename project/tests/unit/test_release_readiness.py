"""Приемка не допускает доступную БД с неправильной Alembic-ревизией."""

from unittest.mock import Mock

from app.api import health


def test_readyz_rejects_wrong_revision(monkeypatch):
    monkeypatch.setattr(health.db, "database_ready", lambda: (True, "ok"))
    monkeypatch.setattr(health.db, "current_revision", lambda: "old_revision")
    directory = Mock()
    directory.get_heads.return_value = ["new_revision"]
    monkeypatch.setattr(health.ScriptDirectory, "from_config", lambda _: directory)
    response = health.readyz(Mock())
    assert response.status_code == 503
    assert b"MIGRATIONS_MISMATCH" in response.body


def test_readyz_accepts_matching_revision(monkeypatch):
    monkeypatch.setattr(health.db, "database_ready", lambda: (True, "ok"))
    monkeypatch.setattr(health.db, "current_revision", lambda: "current_revision")
    directory = Mock()
    directory.get_heads.return_value = ["current_revision"]
    monkeypatch.setattr(health.ScriptDirectory, "from_config", lambda _: directory)
    assert health.readyz(Mock()).status_code == 200
