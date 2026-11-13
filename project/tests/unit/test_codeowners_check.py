"""Критические файлы закреплены в CODEOWNERS (ЛР5, пункты 13–14; ТЗ 7.1)."""

from __future__ import annotations

from types import SimpleNamespace

from scripts import codeowners_check as co

TEXT = """
# комментарий
/.github/               @anna @boris
/project/tests/         @anna @boris @vera
/project/Makefile       @boris @vera   # хвостовой комментарий
/project/requirements*.lock @vera @anna
/project/tests/unit/    @vera @boris
"""

GUARD = SimpleNamespace(
    CRITICAL=("tests/*", "Makefile", "requirements*.lock", "docker/*"),
    CRITICAL_REPO=(".github/*",),
)


def test_rules_are_parsed_without_comments() -> None:
    rules = co.parse(TEXT)

    assert rules[0] == ("/.github/", ["@anna", "@boris"])
    assert rules[2] == ("/project/Makefile", ["@boris", "@vera"])


def test_matching_follows_github_rules() -> None:
    assert co.matches("/.github/", ".github/workflows/ci.yml")
    assert co.matches("/project/requirements*.lock", "project/requirements-dev.lock")
    assert co.matches("/project/Makefile", "project/Makefile")
    assert not co.matches("/project/Makefile", "project/docs/Makefile")
    assert co.matches("*.lock", "project/requirements.lock")


def test_last_matching_rule_wins() -> None:
    rules = co.parse(TEXT)

    assert co.owners_of(rules, "project/tests/unit/test_x.py") == ["@vera", "@boris"]
    assert co.owners_of(rules, "project/tests/integration/test_x.py") == [
        "@anna",
        "@boris",
        "@vera",
    ]
    assert co.owners_of(rules, "project/app/main.py") is None


def test_critical_files_come_from_guard_list() -> None:
    files = [
        "project/tests/unit/test_x.py",
        "project/app/main.py",
        "project/Makefile",
        "project/docker/Dockerfile",
        ".github/workflows/ci.yml",
        "README.md",
    ]

    assert co.critical_files(files, "project/", GUARD) == [
        "project/tests/unit/test_x.py",
        "project/Makefile",
        "project/docker/Dockerfile",
        ".github/workflows/ci.yml",
    ]


def test_complete_codeowners_passes() -> None:
    critical = ["project/tests/unit/test_x.py", "project/Makefile", ".github/workflows/ci.yml"]

    assert co.check(co.parse(TEXT), critical) == []


def test_unowned_critical_file_is_found() -> None:
    problems = co.check(co.parse(TEXT), ["project/docker/Dockerfile"])

    assert problems == [
        "project/docker/Dockerfile: критический файл не закреплён в CODEOWNERS"
    ]


def test_single_owner_is_found() -> None:
    problems = co.check(co.parse("/project/Makefile @anna\n"), [])

    assert any("ответственных 1, нужно не меньше 2" in p for p in problems)


def test_placeholders_and_bad_logins_are_found() -> None:
    problems = co.check(co.parse("/x/ @LOGIN_ANNA @boris\n/y/ @anna @not_a_login!\n"), [])

    assert any("@LOGIN_ANNA" in p and "заглушки" in p for p in problems)
    assert any("@not_a_login!" in p for p in problems)
