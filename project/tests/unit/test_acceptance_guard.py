"""Защита файлов приёмки (ЛР5, пункты 13–15): что считается ослаблением.

Сравнение идёт по текстам «до» и «после»; как сценарий берёт их из git,
показывает make guard. Здесь — правила.
"""

from __future__ import annotations

from scripts import acceptance_guard as guard

TESTS_BEFORE = """
import pytest


def test_area():
    assert 1 == 1
    assert 2 == 2


@pytest.mark.parametrize("value", [1, 2, 3])
def test_cases(value):
    assert value


def test_raises():
    with pytest.raises(ValueError):
        int("x")


class TestGroup:
    def test_inside(self):
        assert True
"""


def test_test_functions_are_counted_with_checks_and_cases() -> None:
    found = guard.collect_test_functions(TESTS_BEFORE)

    assert set(found) == {"test_area", "test_cases", "test_raises", "TestGroup.test_inside"}
    assert found["test_area"].checks == 2
    assert found["test_cases"].cases == 3
    assert found["test_raises"].checks == 1


def test_unchanged_tests_are_not_a_weakening() -> None:
    files = {"tests/unit/test_x.py": TESTS_BEFORE}

    assert guard.compare_tests(files, dict(files), {}) == []


def test_added_test_is_not_a_weakening() -> None:
    after = TESTS_BEFORE + "\n\ndef test_new():\n    assert 3\n"

    assert guard.compare_tests({"tests/t.py": TESTS_BEFORE}, {"tests/t.py": after}, {}) == []


def test_removed_test_is_found() -> None:
    after = TESTS_BEFORE.replace("def test_raises", "def helper_raises")

    findings = guard.compare_tests({"tests/t.py": TESTS_BEFORE}, {"tests/t.py": after}, {})

    assert findings == ["tests/t.py::test_raises: удалён тест"]


def test_removed_assert_is_found() -> None:
    after = TESTS_BEFORE.replace("    assert 2 == 2\n", "")

    findings = guard.compare_tests({"tests/t.py": TESTS_BEFORE}, {"tests/t.py": after}, {})

    assert findings == ["tests/t.py::test_area: проверок стало меньше — 2 → 1"]


def test_removed_parametrize_case_is_found() -> None:
    after = TESTS_BEFORE.replace("[1, 2, 3]", "[1]")

    findings = guard.compare_tests({"tests/t.py": TESTS_BEFORE}, {"tests/t.py": after}, {})

    assert findings == ["tests/t.py::test_cases: случаев parametrize стало меньше — 3 → 1"]


def test_added_skip_is_found_even_with_reason() -> None:
    after = TESTS_BEFORE.replace(
        "def test_area", '@pytest.mark.skip(reason="временно")\ndef test_area'
    )

    findings = guard.compare_tests({"tests/t.py": TESTS_BEFORE}, {"tests/t.py": after}, {})

    assert findings == ["tests/t.py: добавлен пропуск теста (skip, skipif, xfail)"]


def test_deleted_file_is_found_and_rename_is_followed() -> None:
    before = {"tests/old.py": TESTS_BEFORE}

    assert guard.compare_tests(before, {}, {}) == ["tests/old.py: удалён файл тестов"]
    assert (
        guard.compare_tests(
            before, {"tests/new.py": TESTS_BEFORE}, {"tests/old.py": "tests/new.py"}
        )
        == []
    )


MAKEFILE = """\
RUN := bash scripts/run.sh

verify: quality types test ## Полная проверка
\t@echo ok

quality: ## Линтер
\t$(RUN) ruff check .

types: ## Типы
\t$(RUN) mypy app scripts

test: ## Тесты
\t$(RUN) pytest
"""


def test_makefile_targets_are_parsed() -> None:
    targets = guard.parse_makefile(MAKEFILE)

    assert targets["verify"][0] == ["quality", "types", "test"]
    assert targets["types"][1] == ["\t$(RUN) mypy app scripts"]
    assert "RUN" not in targets


def test_makefile_without_changes_passes() -> None:
    assert guard.compare_makefile(MAKEFILE, MAKEFILE) == []


def test_step_removed_from_verify_is_found() -> None:
    after = MAKEFILE.replace("verify: quality types test", "verify: quality test")

    assert guard.compare_makefile(MAKEFILE, after) == [
        "Makefile: из make verify убраны шаги — types"
    ]


def test_suppressed_error_in_check_is_found() -> None:
    for weak in ("|| true", "--exit-zero", "-k 'not slow'", "--deselect tests/x.py"):
        after = MAKEFILE.replace("$(RUN) pytest", f"$(RUN) pytest {weak}")
        findings = guard.compare_makefile(MAKEFILE, after)
        assert len(findings) == 1, weak
        assert findings[0].startswith("Makefile: в make test добавлено ослабление")


def test_report_formatting_flags_are_not_a_weakening() -> None:
    after = MAKEFILE.replace(
        "$(RUN) pytest", "$(RUN) pytest && coverage report --skip-covered"
    )

    assert guard.compare_makefile(MAKEFILE, after) == []


def test_ignored_error_prefix_and_removed_target_are_found() -> None:
    after = MAKEFILE.replace("\t$(RUN) ruff check .", "\t-$(RUN) ruff check .")
    assert guard.compare_makefile(MAKEFILE, after) == [
        "Makefile: в make quality добавлено ослабление — ведущий «-» — make игнорирует ошибку"
    ]

    without_types = MAKEFILE.replace("types: ## Типы\n\t$(RUN) mypy app scripts\n", "")
    assert "Makefile: удалена цель проверки make types" in guard.compare_makefile(
        MAKEFILE, without_types
    )


PYPROJECT = """\
[tool.ruff]
line-length = 95

[tool.ruff.lint]
select = ["E", "F", "B"]
ignore = ["B008"]

[tool.mypy]
warn_unused_configs = true
ignore_missing_imports = false

[tool.bandit]
exclude_dirs = ["tests"]

[tool.coverage.report]
fail_under = 70
"""


def test_pyproject_without_changes_passes() -> None:
    assert guard.compare_pyproject(PYPROJECT, PYPROJECT) == []


def test_pyproject_weakenings_are_found() -> None:
    after = (
        PYPROJECT.replace('select = ["E", "F", "B"]', 'select = ["E", "F"]')
        .replace('ignore = ["B008"]', 'ignore = ["B008", "E501"]')
        .replace("warn_unused_configs = true", "warn_unused_configs = false")
        .replace('exclude_dirs = ["tests"]', 'exclude_dirs = ["tests", "app"]')
        .replace("fail_under = 70", "fail_under = 60")
        .replace("line-length = 95", "line-length = 120")
    )

    findings = guard.compare_pyproject(PYPROJECT, after)

    assert len(findings) == 6
    assert "pyproject.toml: порог покрытия снижен — 70 → 60" in findings
    assert "pyproject.toml: правила ruff (select) — убрано B" in findings


def test_stricter_pyproject_is_not_a_weakening() -> None:
    after = PYPROJECT.replace("fail_under = 70", "fail_under = 80").replace(
        'select = ["E", "F", "B"]', 'select = ["E", "F", "B", "S"]'
    )

    assert guard.compare_pyproject(PYPROJECT, after) == []


SECRET_SCAN = """\
SKIP_DIRS = frozenset({".git", ".venv"})
FORBIDDEN_NAMES = (".env", "id_rsa")
ALLOWED: dict[str, str] = {"docs/testing.md": "примеры"}
"""


def test_new_exception_in_scanner_is_found() -> None:
    after = SECRET_SCAN.replace(
        '{"docs/testing.md": "примеры"}', '{"docs/testing.md": "примеры", "app/x.py": "надо"}'
    )

    findings = guard.compare_scripts(
        {"scripts/secret_scan.py": SECRET_SCAN}, {"scripts/secret_scan.py": after}
    )

    assert findings == ["scripts/secret_scan.py: в ALLOWED добавлены исключения — app/x.py"]


def test_narrowed_forbidden_list_and_lower_threshold_are_found() -> None:
    after = SECRET_SCAN.replace('(".env", "id_rsa")', '(".env",)')
    waiver_old, waiver_new = "REQUIRED_COVERAGE = 70\n", "REQUIRED_COVERAGE = 40\n"

    findings = guard.compare_scripts(
        {"scripts/secret_scan.py": SECRET_SCAN, "scripts/waiver_check.py": waiver_old},
        {"scripts/secret_scan.py": after, "scripts/waiver_check.py": waiver_new},
    )

    assert "scripts/secret_scan.py: из FORBIDDEN_NAMES убрано — id_rsa" in findings
    assert "scripts/waiver_check.py: порог покрытия снижен — 70 → 40" in findings


def test_new_image_scan_exception_is_found() -> None:
    before = "vulnerabilities: []\n"
    after = "vulnerabilities:\n  - id: CVE-2026-1\n    statement: x\n"

    findings = guard.compare_scripts(
        {".trivyignore.yaml": before}, {".trivyignore.yaml": after}
    )

    assert findings == [".trivyignore.yaml: добавлены исключения анализа образа — CVE-2026-1"]


def test_justification_needs_explicit_line() -> None:
    text = "fix: правка\n\nОбоснование-ослабления: тест дублирует test_area и удалён\n"

    assert guard.JUSTIFICATION.findall(text) == ["тест дублирует test_area и удалён"]
    assert guard.JUSTIFICATION.findall("Обоснование-ослабления: надо") == []


def test_skip_mentioned_in_string_is_not_a_skip() -> None:
    source = "TEXT = \"@pytest.mark.skip(reason='x')\"\n\ndef test_a():\n    assert TEXT\n"

    assert guard.count_skips(source) == 0
    assert guard.count_skips("import pytest\npytestmark = pytest.mark.xfail\n") == 1
    assert guard.count_skips("def test_a():\n    pytest.skip('нет базы')\n") == 1
