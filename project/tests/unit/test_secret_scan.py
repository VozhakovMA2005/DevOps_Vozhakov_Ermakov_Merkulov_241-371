"""Поиск секретов (ТЗ 7.2, ЛР5 пункт 12): строки и коммиты ветки.

Вывод git log здесь подаётся готовым текстом: образ проверок не содержит git,
а разбирать надо именно текст. Как сценарий получает этот текст от git,
показывает make secrets-branch.
"""

from __future__ import annotations

from scripts import secret_scan

# Значения собираются по частям: этот файл сам проверяется поиском секретов
VALUE = "Pr0d-" + "Mail-2026!"


def findings_for(relative: str, line: str) -> list[str]:
    found: list[str] = []
    secret_scan.check_line(relative, 1, line, found)
    return found


def test_prefixed_name_is_found() -> None:
    found = findings_for("app/settings.py", f'SMTP_PASSWORD = "{VALUE}"')

    assert found == ["app/settings.py:1: значение «SMTP_PASSWORD» записано строкой"]


def test_plain_name_is_found() -> None:
    assert findings_for("app/settings.py", f'password = "{VALUE}"')


def test_substitutions_and_placeholders_pass() -> None:
    assert findings_for("app/config.py", 'password = os.getenv("DB_PASSWORD")') == []
    assert findings_for("deploy/x.sh", 'OWNER_PASSWORD="$STORED_OWNER"') == []
    assert findings_for("app/x.py", 'token = "CHANGE_ME_please"') == []


def test_word_ending_with_keyword_is_not_a_name() -> None:
    # «compassword» — не имя настройки с приставкой, а просто слово
    assert findings_for("app/x.py", f'compassword = "{VALUE}"') == []


def test_samples_in_tests_are_allowed_but_hard_formats_are_not() -> None:
    assert findings_for("tests/test_x.py", f'password = "{VALUE}"') == []
    key = "-----BEGIN " + "PRIVATE KEY-----"
    assert findings_for("tests/test_x.py", key) == ["tests/test_x.py:1: закрытый ключ"]


LOG = "\n".join(
    [
        "\0commit 1111111111aaaaaaaaaa",
        "diff --git a/app/demo.py b/app/demo.py",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/app/demo.py",
        "@@ -0,0 +1,2 @@",
        "+import os",
        f'+SMTP_PASSWORD = "{VALUE}"',
        "diff --git a/.env.production b/.env.production",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/.env.production",
        "@@ -0,0 +1 @@",
        "+X=1",
        "\0commit 2222222222bbbbbbbbbb",
        "diff --git a/app/demo.py b/app/demo.py",
        "--- a/app/demo.py",
        "+++ b/app/demo.py",
        "@@ -2 +2 @@",
        '+SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")',
        "diff --git a/docs/testing.md b/docs/testing.md",
        "--- a/docs/testing.md",
        "+++ b/docs/testing.md",
        "@@ -10,0 +11 @@",
        f'+password = "{VALUE}"',
        "",
    ]
)


def test_log_is_parsed_with_line_numbers() -> None:
    added = secret_scan.parse_log(LOG)

    assert ("1111111111aaaaaaaaaa", "app/demo.py", 2, f'SMTP_PASSWORD = "{VALUE}"') in added
    assert ("1111111111aaaaaaaaaa", ".env.production", 0, "") in added
    assert ("2222222222bbbbbbbbbb", "docs/testing.md", 11, f'password = "{VALUE}"') in added


def test_secret_removed_in_later_commit_is_still_found() -> None:
    findings, commits = secret_scan.scan_log(LOG)

    assert commits == 2
    assert "коммит 1111111111: app/demo.py:2: значение «SMTP_PASSWORD» записано строкой" in (
        findings
    )
    assert any(".env.production: запрещённый файл" in f for f in findings)
    # исправленная строка второго коммита — подстановка, находки нет
    assert not any(f.startswith("коммит 2222222222: app/demo.py") for f in findings)


def test_allowed_files_are_skipped_in_history_too() -> None:
    findings, _ = secret_scan.scan_log(LOG)

    assert not any("docs/testing.md" in f for f in findings)


def test_clean_log_has_no_findings() -> None:
    findings, _ = secret_scan.scan_log("\0commit 3333\n+++ b/app/x.py\n@@ -1 +1 @@\n+x = 1\n")

    assert findings == []
