"""Разбор отчёта pip-audit (ЛР5, пункт 12). Сеть для этих проверок не нужна."""

from __future__ import annotations

import pytest

from scripts import deps_check

REPORT = {
    "dependencies": [
        {
            "name": "starlette",
            "version": "0.41.3",
            "vulns": [
                {"id": "PYSEC-1", "fix_versions": ["0.47.2"], "aliases": ["CVE-2025-1"]},
                {"id": "PYSEC-2", "fix_versions": [], "aliases": []},
            ],
        },
        # тот же пакет из второго lock-файла: находка не должна удвоиться
        {
            "name": "starlette",
            "version": "0.41.3",
            "vulns": [
                {"id": "PYSEC-1", "fix_versions": ["0.47.2"], "aliases": ["CVE-2025-1"]}
            ],
        },
        {"name": "jinja2", "version": "3.1.6", "vulns": []},
        {"name": "local-pkg", "version": "1.0", "skip_reason": "нет на PyPI"},
    ]
}


def test_findings_are_deduplicated_and_sorted() -> None:
    findings, skipped = deps_check.parse_report(REPORT)

    assert [(f.package, f.vuln_id) for f in findings] == [
        ("starlette", "PYSEC-1"),
        ("starlette", "PYSEC-2"),
    ]
    assert skipped == ["local-pkg: нет на PyPI"]


def test_clean_report_has_no_findings() -> None:
    findings, skipped = deps_check.parse_report(
        {"dependencies": [{"name": "jinja2", "version": "3.1.6", "vulns": []}]}
    )
    assert findings == []
    assert skipped == []


def test_description_names_fix_or_its_absence() -> None:
    findings, _ = deps_check.parse_report(REPORT)

    assert "исправлено в 0.47.2" in findings[0].describe()
    assert "CVE-2025-1" in findings[0].describe()
    assert "исправления нет" in findings[1].describe()


def test_without_exceptions_every_finding_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps_check, "ALLOWED", {})
    findings, _ = deps_check.parse_report(REPORT)

    allowed, blocking = deps_check.split_allowed(findings)

    assert allowed == []
    assert len(blocking) == 2


def test_exception_matches_by_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps_check, "ALLOWED", {"CVE-2025-1": "не используется в проекте"})
    findings, _ = deps_check.parse_report(REPORT)

    allowed, blocking = deps_check.split_allowed(findings)

    assert [f.vuln_id for f in allowed] == ["PYSEC-1"]
    assert [f.vuln_id for f in blocking] == ["PYSEC-2"]
    assert deps_check.reason_for(allowed[0]) == "не используется в проекте"


def test_missing_tool_is_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(deps_check.shutil, "which", lambda name: None)

    assert deps_check.run_pip_audit(tmp_path / "report.json") == 2
