"""Анализ образа (ЛР5, пункт 12): исключения и разбор отчёта Trivy.

Сам сканер здесь не запускается — ему нужны Docker и база уязвимостей.
Проверяется то, что решает судьбу сборки: какие находки блокируют и какие
исключения допустимы.
"""

from __future__ import annotations

import datetime as dt

from scripts import image_scan

TODAY = dt.date(2026, 11, 1)

IGNORE_TEXT = """
# комментарий
vulnerabilities:
  - id: CVE-2026-0001
    statement: "утилита в образе есть, но приложение её не вызывает"
    expired_at: 2026-12-31
  - id: CVE-2026-0002  # без причины
    expired_at: 2026-12-31
  - id: CVE-2026-0003
    statement: 'причина указана, а срок уже прошёл'
    expired_at: 2026-10-01
  - id: CVE-2026-0004
    statement: "причина указана, срока нет вовсе"
"""

REPORT = {
    "Results": [
        {
            "Target": "audfond (debian 13.1)",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-1000",
                    "PkgName": "libssl3t64",
                    "InstalledVersion": "3.5.1-1",
                    "FixedVersion": "3.5.1-1+deb13u1",
                    "Severity": "HIGH",
                },
                {
                    "VulnerabilityID": "CVE-2026-1001",
                    "PkgName": "libc6",
                    "InstalledVersion": "2.41-12",
                    "FixedVersion": "",
                    "Severity": "CRITICAL",
                },
                {
                    "VulnerabilityID": "CVE-2026-1002",
                    "PkgName": "zlib1g",
                    "InstalledVersion": "1:1.3",
                    "FixedVersion": "1:1.3.1",
                    "Severity": "MEDIUM",
                },
            ],
        },
        {
            "Target": "Python",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-2000",
                    "PkgName": "pip",
                    "InstalledVersion": "24.3.1",
                    "FixedVersion": "25.3",
                    "Severity": "CRITICAL",
                }
            ],
        },
        {"Target": "пустой слой", "Vulnerabilities": None},
    ]
}


def test_ignore_file_is_parsed() -> None:
    entries = image_scan.parse_ignore_file(IGNORE_TEXT)

    assert [e.vuln_id for e in entries] == [
        "CVE-2026-0001",
        "CVE-2026-0002",
        "CVE-2026-0003",
        "CVE-2026-0004",
    ]
    assert entries[0].statement.startswith("утилита")
    assert entries[2].statement == "причина указана, а срок уже прошёл"


def test_empty_ignore_file_has_no_entries() -> None:
    assert image_scan.parse_ignore_file("vulnerabilities: []\n") == []


def test_only_justified_unexpired_exception_passes() -> None:
    entries = image_scan.parse_ignore_file(IGNORE_TEXT)

    problems = image_scan.check_ignore_entries(entries, TODAY)

    assert not any(p.startswith("CVE-2026-0001") for p in problems)
    assert any(p.startswith("CVE-2026-0002") and "причины" in p for p in problems)
    assert any(p.startswith("CVE-2026-0003") and "истёк" in p for p in problems)
    assert any(p.startswith("CVE-2026-0004") and "срока" in p for p in problems)


def test_report_is_sorted_by_severity() -> None:
    vulns = image_scan.parse_report(REPORT)

    assert [v.severity for v in vulns] == ["CRITICAL", "CRITICAL", "HIGH", "MEDIUM"]


def test_only_fixable_high_and_critical_block() -> None:
    vulns = image_scan.parse_report(REPORT)

    stop = image_scan.blocking(vulns, {"HIGH", "CRITICAL"})

    assert {v.vuln_id for v in stop} == {"CVE-2026-1000", "CVE-2026-2000"}


def test_clean_report_blocks_nothing() -> None:
    vulns = image_scan.parse_report({"Results": [{"Target": "x", "Vulnerabilities": []}]})

    assert image_scan.blocking(vulns, {"HIGH", "CRITICAL"}) == []


def test_tracker_version_is_pinned() -> None:
    name, _, tag = image_scan.TRIVY_IMAGE.rpartition(":")
    assert name == "aquasec/trivy"
    assert tag != "latest" and tag[0].isdigit()
