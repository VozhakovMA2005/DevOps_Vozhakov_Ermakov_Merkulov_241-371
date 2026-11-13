"""Защита критических файлов приёмки — ЛР5, пункты 13–15; ТЗ 7.1, 7.2.

Команда make guard. Сравнивает ветку с основной (общий предок с BASE, по
умолчанию origin/main) и ищет ослабление проверок:

    тесты      удалён файл тестов или тест; в тесте стало меньше проверок
               (assert, pytest.raises) или случаев parametrize; добавлен
               пропуск или xfail
    Makefile   из make verify убран шаг; удалена цель проверки; в команду
               проверки добавлено подавление ошибки (|| true, --exit-zero,
               --no-cov, -k, --deselect, ведущий «-» и подобное)
    настройки  pyproject.toml: убрано правило линтера или добавлено
               исключение; ослаблен mypy; расширены исключения bandit и
               покрытия; снижен порог покрытия
    сценарии   снижен порог в waiver_check.py; добавлены исключения в
               secret_scan.py, deps_check.py, .trivyignore.yaml; в
               container_check.py стало меньше проверок

Изменённые критические файлы перечисляются отдельно: их одобряет ответственный
участник (CODEOWNERS или правило согласования CI-системы).

Ослабление не принимается незаметно. Если оно действительно нужно, в сообщении
одного из коммитов ветки пишется строка

    Обоснование-ослабления: <почему, не короче 20 знаков>

Тогда проверка проходит, но выводит каждое ослабление и обоснование: решение
принимает ревьюер критических файлов, а не автор.

Make запускает этот сценарий в той редакции, что уже лежит в BASE, а не в
ветке: ослабить саму проверку в том же запросе на слияние нельзя.

Коды возврата: 0 — ослаблений нет или все обоснованы, 1 — есть ослабление без
обоснования, 2 — проверка не выполнена (нет git, нет BASE).

Только стандартная библиотека: запускается на машине, в том числе из файла
вне проекта (git show BASE:… > файл).

    python3 scripts/acceptance_guard.py --base origin/main
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import shutil
import subprocess  # nosec B404  # опрос git: служебный сценарий проверок
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JUSTIFICATION = re.compile(r"^Обоснование-ослабления:\s*(.{20,})$", re.MULTILINE)

#: Критические файлы проекта (пути относительно каталога проекта). Все
#: сценарии scripts/ — критические: через них идут сами проверки (run.sh,
#: lib.sh, migrate_drill.sh), и правка любого из них может проверку отключить.
#: Файлы настроек инструментов — тоже: ruff, mypy, pytest и coverage читают
#: ruff.toml, mypy.ini, pytest.ini, .coveragerc раньше pyproject.toml
CRITICAL = (
    "tests/*",
    "scripts/*",
    "Makefile",
    "pyproject.toml",
    "*.toml",
    "*.ini",
    "*.cfg",
    ".coveragerc",
    "*conftest.py",
    "sitecustomize.py",
    "docker/*",
    "docker-compose.yml",
    ".dockerignore",
    "requirements*.txt",
    "requirements*.lock",
    ".trivyignore.yaml",
    "deploy/*",
    "migrations/env.py",
    "CONTRIBUTING.md",
)
#: Критические файлы в корне репозитория: настройки CI и правила согласования
CRITICAL_REPO = (
    ".github/*",
    ".gitlab-ci.yml",
    ".gitlab/*",
    "Jenkinsfile",
    "CODEOWNERS",
    "docs/CODEOWNERS",
)

#: Цели make, удаление которых — ослабление
CHECK_TARGETS = (
    "verify",
    "quality",
    "types",
    "sast",
    "secrets",
    "secrets-branch",
    "waivers",
    "migrate-check",
    "test",
    "test-report",
    "coverage-services",
    "mutants",
    "migrate-drill",
    "restore-drill",
    "deps-check",
    "image-scan",
    "container-check",
    "guard",
    "ci",
    "push",
    "publish",
    "test-unit",
    "test-int",
    "schema-check",
    "secrets-scan",
    "ci-sync",
    "codeowners-check",
    "build-app",
)

#: Переменные Makefile, из которых собираются команды проверок
CHECK_VARIABLES = (
    "SHELL",
    "LOCAL",
    "DOCKER_READY",
    "COMPOSE",
    "RUN",
    "DRILL_PREFIX",
    "MIGRATE_CMD",
    "DEPS_CMD",
    "DEPS_PRE",
    "GUARD_PATH",
)

#: Файлы настроек, которые инструменты проверок читают раньше pyproject.toml
#: или подключают сами. Появление такого файла меняет поведение проверки
#: в обход pyproject.toml
TOOL_CONFIGS = frozenset(
    {
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".mypy.ini",
        "pytest.ini",
        ".pytest.ini",
        "tox.ini",
        "setup.cfg",
        ".coveragerc",
        ".bandit",
        ".flake8",
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
    }
)

#: Сценарии, через которые запускаются сами проверки: правка любого из них
#: может отключить проверку целиком (например, run.sh выходит с 0 вместо
#: запуска pytest). Любое изменение — только с обоснованием
RUNNER_SCRIPTS = (
    "scripts/run.sh",
    "scripts/lib.sh",
    "scripts/migrate_drill.sh",
    "scripts/restore_drill.sh",
    "scripts/ci_local.sh",
    "scripts/ci_base.sh",
)

#: Перехватчики pytest, которыми можно убрать или подменить тесты
PYTEST_HOOKS = re.compile(
    r"^\s*def\s+(pytest_collection_modifyitems|pytest_ignore_collect|pytest_collect_file|"
    r"pytest_pycollect_makeitem|pytest_runtest_setup|pytest_runtest_call|"
    r"pytest_runtest_makereport|pytest_configure|pytest_report_teststatus)\b",
    re.MULTILINE,
)

#: Подавление ошибки или сужение проверки в команде make: метка -> образец
WEAK_RECIPE = (
    ("«|| true» — ошибка подавлена", re.compile(r"\|\|\s*(true|:)\b")),
    ("«; true» — ошибка подавлена", re.compile(r";\s*true\b")),
    ("ведущий «-» — make игнорирует ошибку", re.compile(r"^\t-")),
    ("--exit-zero", re.compile(r"--exit-zero")),
    ("--exit-code 0", re.compile(r"--exit-code[ =]0\b")),
    ("--no-cov", re.compile(r"--no-cov(?![\w-])")),
    ("--cov-fail-under", re.compile(r"--cov-fail-under")),
    ("отбор тестов -k", re.compile(r"\s-k\s")),
    ("--deselect", re.compile(r"--deselect")),
    ("--ignore", re.compile(r"--ignore(?:-glob)?[ =]")),
    ("--ignore-vuln", re.compile(r"--ignore-vuln")),
    ("-p no:", re.compile(r"-p\s+no:")),
    # не --skip-covered: тот лишь сокращает вывод отчёта покрытия
    ("--skip", re.compile(r"--skip(?![\w-])")),
    ("--continue-on-collection-errors", re.compile(r"--continue-on-collection-errors")),
)


MYPY_STRICT_ON = (
    "strict",
    "disallow_untyped_defs",
    "disallow_incomplete_defs",
    "check_untyped_defs",
    "disallow_any_generics",
    "warn_return_any",
    "warn_unused_ignores",
    "warn_unused_configs",
    "no_implicit_optional",
    "strict_optional",
    "strict_equality",
)
MYPY_STRICT_OFF = ("ignore_missing_imports", "ignore_errors", "allow_untyped_defs")

#: Константы сценариев, расширение которых — новое исключение: файл -> имена
EXCEPTION_SETS = {
    "scripts/secret_scan.py": (
        "ALLOWED",
        "SKIP_DIRS",
        "SKIP_SUFFIXES",
        "PLACEHOLDERS",
        "SAFE_VALUE_MARKERS",
        "SAMPLE_PREFIXES",
    ),
    "scripts/deps_check.py": ("ALLOWED",),
}
#: Константы, сужение которых — ослабление: файл -> имена
REQUIRED_SETS = {
    "scripts/secret_scan.py": ("FORBIDDEN_NAMES", "FORBIDDEN_SUFFIXES"),
    "scripts/waiver_check.py": ("SCAN_DIRS",),
}


# --------------------------------------------------------------------------- #
# Тесты
# --------------------------------------------------------------------------- #


@dataclass
class CaseInfo:
    checks: int = 0
    cases: int = 0


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.startswith("test_") and name.endswith(".py")


def always_true(test: ast.expr) -> bool:
    """assert, который не может упасть: assert True, assert 1, assert True or …"""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(isinstance(v, ast.Constant) and bool(v.value) for v in test.values)
    return False


def count_checks(node: ast.AST) -> int:
    """assert и pytest.raises / pytest.warns внутри функции.

    Заведомо истинный assert проверкой не считается: «assert True or x == 1»
    выглядит как проверка, но не падает никогда.
    """
    total = 0
    for child in ast.walk(node):
        is_raises = (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in {"raises", "warns"}
        )
        if (isinstance(child, ast.Assert) and not always_true(child.test)) or is_raises:
            total += 1
    return total


def count_skips(source: str) -> int:
    """Пропуски в коде тестов: маркеры skip, skipif, xfail и вызовы skip(), xfail() из pytest.

    Считаются узлы синтаксического дерева, а не текст: упоминание в строке или
    комментарии пропуском не является.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        if (
            node.attr in {"skip", "skipif", "xfail"}
            and isinstance(owner, ast.Attribute)
            and owner.attr == "mark"
        ) or (
            node.attr in {"skip", "xfail"}
            and isinstance(owner, ast.Name)
            and owner.id == "pytest"
        ):
            total += 1
    return total


def count_cases(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Число случаев во всех @pytest.mark.parametrize функции."""
    total = 0
    for deco in func.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr == "parametrize"
            and len(deco.args) >= 2
            and isinstance(deco.args[1], ast.List | ast.Tuple)
        ):
            total += len(deco.args[1].elts)
    return total


def collect_test_functions(source: str) -> dict[str, CaseInfo]:
    """Тесты файла: имя (с классом) -> число проверок и случаев."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, CaseInfo] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
                node.name.startswith("test")
            ):
                found[f"{prefix}{node.name}"] = CaseInfo(count_checks(node), count_cases(node))

    visit(tree.body, "")
    return found


def compare_tests(
    base: dict[str, str],
    head: dict[str, str],
    renames: dict[str, str],
) -> list[str]:
    """Ослабления тестов. base и head: путь -> текст; renames: старый -> новый путь."""
    findings: list[str] = []
    for path, old_source in sorted(base.items()):
        new_path = renames.get(path, path)
        if new_path not in head:
            findings.append(f"{path}: удалён файл тестов")
            continue
        new_source = head[new_path]
        old_tests, new_tests = (
            collect_test_functions(old_source),
            collect_test_functions(new_source),
        )
        shown = path if new_path == path else f"{path} → {new_path}"
        for name, old in sorted(old_tests.items()):
            new = new_tests.get(name)
            if new is None:
                findings.append(f"{shown}::{name}: удалён тест")
                continue
            if new.checks < old.checks:
                findings.append(
                    f"{shown}::{name}: проверок стало меньше — {old.checks} → {new.checks}"
                )
            if new.cases < old.cases:
                findings.append(
                    f"{shown}::{name}: случаев parametrize стало меньше — "
                    f"{old.cases} → {new.cases}"
                )
        if count_skips(new_source) > count_skips(old_source):
            findings.append(f"{shown}: добавлен пропуск теста (skip, skipif, xfail)")
    for path, source in sorted(head.items()):
        if path not in base and path not in renames.values() and count_skips(source):
            findings.append(f"{path}: новый файл тестов с пропуском (skip, skipif, xfail)")
    return findings


def count_tests(sources: dict[str, str]) -> int:
    return sum(len(collect_test_functions(text)) for text in sources.values())


# --------------------------------------------------------------------------- #
# Makefile
# --------------------------------------------------------------------------- #


def parse_makefile(text: str) -> dict[str, tuple[list[str], list[str]]]:
    """Цель -> (зависимости, строки команд).

    Строка команды начинается с табуляции и относится к последней цели.
    Любая другая значимая строка (переменная, условие) закрывает цель.
    """
    targets: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None:
                targets[current][1].append(line)
            continue
        if not line.strip() or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=:])\s*(.*)$", line)
        if match and not line.startswith((".PHONY", "export")):
            current = match.group(1)
            targets[current] = (match.group(2).split("##", 1)[0].split(), [])
        else:
            current = None
    return targets


def weak_marks(lines: list[str]) -> Counter[str]:
    marks: Counter[str] = Counter()
    for line in lines:
        for label, pattern in WEAK_RECIPE:
            if pattern.search(line):
                marks[label] += 1
    return marks


def tokens(lines: list[str]) -> set[str]:
    """Слова команды без кавычек и обратных косых.

    Префиксы строки рецепта make (@ — не печатать, - — игнорировать ошибку,
    + — выполнять всегда) отбрасываются: они не часть команды, а «-» ловит
    WEAK_RECIPE отдельно. Сообщения echo и printf не считаются: их текст
    можно менять свободно.
    """
    words: set[str] = set()
    for line in lines:
        line = line.lstrip("\t ").lstrip("@-+")
        for segment in re.split(r"&&|\|\||;|\|", line):
            found = re.findall(r"[^\s\"'\\]+", segment)
            if found and found[0].lstrip("@") in {"echo", "printf"}:
                continue
            words.update(found)
    return words


def parse_variables(text: str) -> dict[str, list[str]]:
    """Переменная -> значения всех её определений (в том числе в ветках ifeq)."""
    joined = re.sub(r"\\\n", " ", text)
    found: dict[str, list[str]] = {}
    for line in joined.splitlines():
        match = re.match(
            r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|\?=|\+=|=)\s*(.*)$", line
        )
        if match:
            found.setdefault(match.group(1), []).append(match.group(2))
    return found


def compare_makefile(base_text: str, head_text: str) -> list[str]:
    base, head = parse_makefile(base_text), parse_makefile(head_text)
    findings: list[str] = []
    # Из команды проверки нельзя убрать часть незаметно: «--fail-under=80» →
    # «--fail-under=0», рецепт quality → «echo ok». Добавлять можно
    for target in CHECK_TARGETS:
        if target in base and target in head:
            removed = tokens(base[target][1]) - tokens(head[target][1])
            if removed:
                findings.append(
                    f"Makefile: из команды make {target} убрано — {', '.join(sorted(removed))}"
                )
    old_vars, new_vars = parse_variables(base_text), parse_variables(head_text)
    for name in CHECK_VARIABLES:
        if name in old_vars:
            removed = tokens(old_vars[name]) - tokens(new_vars.get(name, []))
            if removed:
                findings.append(
                    f"Makefile: из переменной {name} убрано — {', '.join(sorted(removed))}"
                )
    if "verify" in base and "verify" in head:
        dropped = [p for p in base["verify"][0] if p not in head["verify"][0]]
        if dropped:
            findings.append(f"Makefile: из make verify убраны шаги — {', '.join(dropped)}")
    for target in CHECK_TARGETS:
        if target in base and target not in head:
            findings.append(f"Makefile: удалена цель проверки make {target}")
    for target, (_, recipe) in sorted(head.items()):
        old = weak_marks(base[target][1]) if target in base else Counter()
        new = weak_marks(recipe)
        for label, count in sorted(new.items()):
            if count > old.get(label, 0):
                findings.append(f"Makefile: в make {target} добавлено ослабление — {label}")
    return findings


# --------------------------------------------------------------------------- #
# pyproject.toml
# --------------------------------------------------------------------------- #


def dig(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def as_set(value: Any) -> set[str]:
    if isinstance(value, list | tuple | set | frozenset):
        return {str(v) for v in value}
    return set()


def compare_pyproject(base_text: str, head_text: str) -> list[str]:
    try:
        base, head = tomllib.loads(base_text), tomllib.loads(head_text)
    except tomllib.TOMLDecodeError as exc:
        return [f"pyproject.toml: файл не разбирается — {exc}"]
    findings: list[str] = []

    def grew(label: str, *keys: str) -> None:
        added = as_set(dig(head, *keys)) - as_set(dig(base, *keys))
        if added:
            findings.append(f"pyproject.toml: {label} — добавлено {', '.join(sorted(added))}")

    def shrank(label: str, *keys: str) -> None:
        removed = as_set(dig(base, *keys)) - as_set(dig(head, *keys))
        if removed:
            findings.append(f"pyproject.toml: {label} — убрано {', '.join(sorted(removed))}")

    shrank("правила ruff (select)", "tool", "ruff", "lint", "select")
    grew("исключения правил ruff (ignore)", "tool", "ruff", "lint", "ignore")
    grew("исключённые из ruff пути", "tool", "ruff", "extend-exclude")
    grew("исключённые из ruff пути", "tool", "ruff", "exclude")
    old_pfi = dig(base, "tool", "ruff", "lint", "per-file-ignores") or {}
    new_pfi = dig(head, "tool", "ruff", "lint", "per-file-ignores") or {}
    for pattern, codes in sorted(new_pfi.items()):
        added = as_set(codes) - as_set(old_pfi.get(pattern, []))
        if added:
            findings.append(
                f"pyproject.toml: исключения ruff для {pattern} — добавлено "
                f"{', '.join(sorted(added))}"
            )
    old_len = dig(base, "tool", "ruff", "line-length")
    new_len = dig(head, "tool", "ruff", "line-length")
    if isinstance(old_len, int) and isinstance(new_len, int) and new_len > old_len:
        findings.append(f"pyproject.toml: длина строки ruff увеличена — {old_len} → {new_len}")

    for key in MYPY_STRICT_ON:
        if (
            dig(base, "tool", "mypy", key) is True
            and dig(head, "tool", "mypy", key) is not True
        ):
            findings.append(f"pyproject.toml: в mypy выключено {key}")
    for key in MYPY_STRICT_OFF:
        if (
            dig(base, "tool", "mypy", key) is not True
            and dig(head, "tool", "mypy", key) is True
        ):
            findings.append(f"pyproject.toml: в mypy включено {key}")
    grew("исключённые из mypy пути", "tool", "mypy", "exclude")
    old_over = dig(base, "tool", "mypy", "overrides") or []
    new_over = dig(head, "tool", "mypy", "overrides") or []
    if len(new_over) > len(old_over):
        findings.append("pyproject.toml: добавлены исключения mypy (overrides)")

    grew("исключённые из bandit каталоги", "tool", "bandit", "exclude_dirs")
    grew("пропускаемые проверки bandit (skips)", "tool", "bandit", "skips")

    old_cov = dig(base, "tool", "coverage", "report", "fail_under")
    new_cov = dig(head, "tool", "coverage", "report", "fail_under")
    if isinstance(old_cov, int | float) and (
        not isinstance(new_cov, int | float) or new_cov < old_cov
    ):
        findings.append(f"pyproject.toml: порог покрытия снижен — {old_cov} → {new_cov}")
    grew("исключённые из покрытия файлы (omit)", "tool", "coverage", "run", "omit")
    grew("исключённые из покрытия строки", "tool", "coverage", "report", "exclude_lines")

    shrank("каталоги тестов (testpaths)", "tool", "pytest", "ini_options", "testpaths")
    grew(
        "исключённые из сбора тестов каталоги",
        "tool",
        "pytest",
        "ini_options",
        "norecursedirs",
    )
    old_opts = str(dig(base, "tool", "pytest", "ini_options", "addopts") or "")
    new_opts = str(dig(head, "tool", "pytest", "ini_options", "addopts") or "")
    for label, count in sorted(weak_marks([new_opts]).items()):
        if count > weak_marks([old_opts]).get(label, 0):
            findings.append(f"pyproject.toml: в addopts pytest добавлено ослабление — {label}")
    return findings


# --------------------------------------------------------------------------- #
# Сценарии проверок
# --------------------------------------------------------------------------- #


def constants(source: str) -> dict[str, Any]:
    """Значения констант верхнего уровня, записанных литералами."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, Any] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"frozenset", "set", "tuple"}
            and value.args
        ):
            value = value.args[0]
        try:
            found[target.id] = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
    return found


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(k) for k in value}
    return as_set(value)


def compare_scripts(base: dict[str, str], head: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for path, names in EXCEPTION_SETS.items():
        if path not in base or path not in head:
            continue
        old, new = constants(base[path]), constants(head[path])
        for name in names:
            added = keys_of(new.get(name)) - keys_of(old.get(name))
            if added:
                findings.append(
                    f"{path}: в {name} добавлены исключения — {', '.join(sorted(added))}"
                )
    for path, names in REQUIRED_SETS.items():
        if path not in base or path not in head:
            continue
        old, new = constants(base[path]), constants(head[path])
        for name in names:
            removed = keys_of(old.get(name)) - keys_of(new.get(name))
            if removed:
                findings.append(f"{path}: из {name} убрано — {', '.join(sorted(removed))}")

    if "scripts/waiver_check.py" in base and "scripts/waiver_check.py" in head:
        old_req = constants(base["scripts/waiver_check.py"]).get("REQUIRED_COVERAGE")
        new_req = constants(head["scripts/waiver_check.py"]).get("REQUIRED_COVERAGE")
        if isinstance(old_req, int) and (not isinstance(new_req, int) or new_req < old_req):
            findings.append(
                f"scripts/waiver_check.py: порог покрытия снижен — {old_req} → {new_req}"
            )

    if "scripts/image_scan.py" in base and "scripts/image_scan.py" in head:
        old_sev = set(
            str(constants(base["scripts/image_scan.py"]).get("SEVERITY", "")).split(",")
        )
        new_sev = set(
            str(constants(head["scripts/image_scan.py"]).get("SEVERITY", "")).split(",")
        )
        if old_sev - new_sev:
            findings.append(
                "scripts/image_scan.py: из порога анализа образа убраны уровни — "
                + ", ".join(sorted(old_sev - new_sev))
            )

    if "scripts/container_check.py" in base and "scripts/container_check.py" in head:
        old_n = base["scripts/container_check.py"].count("r.check(")
        new_n = head["scripts/container_check.py"].count("r.check(")
        if new_n < old_n:
            findings.append(
                "scripts/container_check.py: проверок окружения стало меньше — "
                f"{old_n} → {new_n}"
            )

    if ".trivyignore.yaml" in head:
        pattern = re.compile(r"^\s*-\s+id:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
        old_ids = set(pattern.findall(base.get(".trivyignore.yaml", "")))
        added = set(pattern.findall(head[".trivyignore.yaml"])) - old_ids
        if added:
            findings.append(
                f".trivyignore.yaml: добавлены исключения анализа образа — "
                f"{', '.join(sorted(added))}"
            )
    return findings


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #


@dataclass
class Repo:
    project: Path
    prefix: str = ""
    merge_base: str = ""
    changes: list[tuple[str, str, str]] = field(default_factory=list)

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        binary = shutil.which("git")
        if binary is None:
            raise FileNotFoundError("git")
        return subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
            [binary, *args], cwd=self.project, capture_output=True, text=True, check=False
        )

    def base_file(self, path: str) -> str | None:
        shown = self.git("show", f"{self.merge_base}:{self.prefix}{path}")
        return shown.stdout if shown.returncode == 0 else None

    def head_file(self, path: str) -> str | None:
        target = self.project / path
        return target.read_text(encoding="utf-8") if target.is_file() else None

    def base_tests(self) -> list[str]:
        listed = self.git("ls-tree", "-r", "--name-only", self.merge_base, "--", "tests")
        names = [n.removeprefix(self.prefix) for n in listed.stdout.splitlines()]
        return [n for n in names if is_test_file(n)]


def open_repo(project: Path, base: str) -> Repo | str:
    repo = Repo(project=project)
    try:
        inside = repo.git("rev-parse", "--show-prefix")
    except FileNotFoundError:
        return "нужен git: проверка сравнивает ветку с основной"
    if inside.returncode != 0:
        return f"{project} — не рабочая копия git"
    repo.prefix = inside.stdout.strip()
    found = repo.git("merge-base", base, "HEAD")
    if found.returncode != 0:
        return (
            f"не найден общий предок с {base}. Получите основную ветку: git fetch origin main"
        )
    repo.merge_base = found.stdout.strip()
    # Изменения рабочего дерева относительно общего предка, по всему репозиторию
    diff = repo.git("diff", "--name-status", "-M", repo.merge_base, "--", ":/")
    for line in diff.stdout.splitlines():
        parts = line.split("\t")
        status = parts[0][:1]
        old = parts[1]
        new = parts[2] if len(parts) > 2 else parts[1]
        repo.changes.append((status, old, new))
    return repo


def critical_changes(repo: Repo) -> list[str]:
    changed = []
    for status, old, new in repo.changes:
        for path in {old, new}:
            if path.startswith(repo.prefix):
                inner = path[len(repo.prefix) :]
                if any(fnmatch.fnmatch(inner, p) for p in CRITICAL):
                    changed.append(f"{status} {inner}")
            elif any(fnmatch.fnmatch(path, p) for p in CRITICAL_REPO):
                changed.append(f"{status} {path} (корень репозитория)")
    return sorted(set(changed))


def justifications(repo: Repo) -> list[str]:
    log = repo.git("log", "--format=%B%x00", f"{repo.merge_base}..HEAD")
    return [m.strip() for m in JUSTIFICATION.findall(log.stdout)]


def collect(repo: Repo) -> tuple[list[str], int, int]:
    """Ослабления, число тестов до и после."""
    renames = {}
    for status, old, new in repo.changes:
        if status == "R" and old.startswith(repo.prefix):
            renames[old[len(repo.prefix) :]] = new[len(repo.prefix) :]

    base_tests = {p: repo.base_file(p) or "" for p in repo.base_tests()}
    head_tests = {
        p.relative_to(repo.project).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((repo.project / "tests").rglob("test_*.py"))
    }
    findings = compare_tests(base_tests, head_tests, renames)

    pairs = {}
    for path in ("Makefile", "pyproject.toml", ".trivyignore.yaml", *EXCEPTION_SETS):
        pairs[path] = (repo.base_file(path), repo.head_file(path))
    for path in (
        "scripts/waiver_check.py",
        "scripts/image_scan.py",
        "scripts/container_check.py",
    ):
        pairs[path] = (repo.base_file(path), repo.head_file(path))

    make_old, make_new = pairs["Makefile"]
    if make_old is not None:
        findings += (
            ["Makefile: удалён"] if make_new is None else compare_makefile(make_old, make_new)
        )
    py_old, py_new = pairs["pyproject.toml"]
    if py_old is not None:
        findings += (
            ["pyproject.toml: удалён"] if py_new is None else compare_pyproject(py_old, py_new)
        )
    base_scripts = {p: old for p, (old, _) in pairs.items() if old is not None}
    head_scripts = {p: new for p, (_, new) in pairs.items() if new is not None}
    for path in base_scripts:
        if path not in head_scripts and path != ".trivyignore.yaml":
            findings.append(f"{path}: удалён сценарий проверки")
    findings += compare_scripts(base_scripts, head_scripts)
    findings += tool_config_changes(repo)
    return findings, count_tests(base_tests), count_tests(head_tests)


def tool_config_changes(repo: Repo) -> list[str]:
    """Новые файлы настроек инструментов и новые перехватчики pytest."""
    findings: list[str] = []
    for status, _old, new in repo.changes:
        if not new.startswith(repo.prefix):
            continue
        inner = new[len(repo.prefix) :]
        name = inner.rsplit("/", 1)[-1]
        if status in {"M", "D", "R"} and _old[len(repo.prefix) :] in RUNNER_SCRIPTS:
            findings.append(
                f"{_old[len(repo.prefix) :]}: изменён сценарий запуска проверок — через него "
                "идут сами проверки"
            )
        if status == "A" and (name in TOOL_CONFIGS or name.endswith(".pth")):
            findings.append(
                f"{inner}: новый файл настроек проверок — инструменты читают его в обход "
                "pyproject.toml"
            )
        if name == "conftest.py" and status in {"M", "R"}:
            before = repo.base_file(_old[len(repo.prefix) :]) or ""
            after = repo.head_file(inner) or ""
            if len(PYTEST_HOOKS.findall(after)) > len(PYTEST_HOOKS.findall(before)):
                findings.append(
                    f"{inner}: добавлен перехватчик pytest — им можно убрать "
                    "или подменить тесты"
                )
    return findings


# --------------------------------------------------------------------------- #
# Вывод
# --------------------------------------------------------------------------- #


def render(
    base: str,
    findings: list[str],
    reasons: list[str],
    critical: list[str],
    tests_before: int,
    tests_after: int,
) -> str:
    lines = [f"# Защита файлов приёмки: ветка против {base}", ""]
    lines.append(f"Тестов: {tests_before} → {tests_after}")
    lines.append("")
    lines.append("## Ослабления проверок")
    lines += [f"- {f}" for f in findings] or ["- нет"]
    if findings:
        lines.append("")
        lines.append("## Обоснование в коммитах ветки")
        lines += [f"- {r}" for r in reasons] or ["- нет — ослабление не принимается"]
    lines.append("")
    lines.append("## Изменены критические файлы — нужно одобрение ответственного")
    lines += [f"- {c}" for c in critical] or ["- нет"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Защита критических файлов приёмки")
    parser.add_argument("--base", default="origin/main", help="основная ветка")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="каталог проекта")
    parser.add_argument("--report", type=Path, help="отчёт в формате Markdown")
    args = parser.parse_args()

    repo = open_repo(args.project_dir.resolve(), args.base)
    if isinstance(repo, str):
        print(f"Проверка не выполнена: {repo}", file=sys.stderr)
        return 2

    findings, before, after = collect(repo)
    reasons = justifications(repo) if findings else []
    critical = critical_changes(repo)
    report = render(args.base, findings, reasons, critical, before, after)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")

    print(
        f"Сравнение с {args.base} (общий предок {repo.merge_base[:10]}); "
        f"тестов: {before} → {after}"
    )
    if critical:
        print("Изменены критические файлы — нужно одобрение ответственного участника:")
        for item in critical:
            print(f"  {item}")

    if not findings:
        print("Ослаблений проверок нет")
        return 0

    stream = sys.stdout if reasons else sys.stderr
    print(f"Ослаблений проверок: {len(findings)}", file=stream)
    for finding in findings:
        print(f"  {finding}", file=stream)
    if reasons:
        print("Ослабление принято с обоснованием из коммита ветки:")
        for reason in reasons:
            print(f"  {reason}")
        print(
            "Решение — за ревьюером критических файлов: обоснование видно "
            "в запросе на слияние."
        )
        return 0
    print(
        "\nОслабление проверок незаметно не принимается (ТЗ 7.2). Верните проверку или, "
        "если ослабление действительно нужно, добавьте в сообщение коммита строку\n"
        "  Обоснование-ослабления: <почему>\n"
        "и получите одобрение ответственного за критические файлы.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
