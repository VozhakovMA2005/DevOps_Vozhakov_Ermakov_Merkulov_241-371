"""Критические файлы закреплены в CODEOWNERS — ЛР5, пункты 13–14; ТЗ 7.1.

Команда make codeowners-check (стадия guard). Проверяет .github/CODEOWNERS:

    1. каждый критический файл репозитория (список CRITICAL и CRITICAL_REPO
       в acceptance_guard.py — один источник) закреплён хотя бы одним
       правилом: изменение без одобрения ответственного не пройдёт;
    2. у каждого правила не меньше двух ответственных: автор запроса на
       слияние сам себя одобрить не может, одобряет второй;
    3. ответственные записаны как логины GitHub, заглушки LOGIN_… заменены.

Сопоставление путей — как у GitHub: путь с «/» в начале отсчитывается от
корня репозитория, «/» в конце — каталог целиком, «*» — любые символы. Из
правил, подошедших к файлу, действует последнее.

Только стандартная библиотека.

    python3 scripts/codeowners_check.py
"""

from __future__ import annotations

import fnmatch
import importlib.util
import re
import shutil
import subprocess  # nosec B404  # опрос git: служебный сценарий проверок
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CODEOWNERS = ROOT.parent / ".github" / "CODEOWNERS"
OWNER = re.compile(r"^@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:/[A-Za-z0-9._-]+)?$")
PLACEHOLDER = re.compile(r"LOGIN_", re.IGNORECASE)
MIN_OWNERS = 2


def load_guard() -> ModuleType:
    """Список критических файлов — из acceptance_guard.py, без копии здесь."""
    spec = importlib.util.spec_from_file_location(
        "acceptance_guard", Path(__file__).with_name("acceptance_guard.py")
    )
    if spec is None or spec.loader is None:
        raise ImportError("acceptance_guard.py")
    module = importlib.util.module_from_spec(spec)
    # Модуль регистрируется до выполнения: dataclass ищет его в sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse(text: str) -> list[tuple[str, list[str]]]:
    rules = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append((pattern, owners))
    return rules


def matches(pattern: str, path: str) -> bool:
    anchored = pattern.startswith("/")
    body = pattern.lstrip("/")
    if body.endswith("/"):
        prefix = body
        return path.startswith(prefix) if anchored else f"/{prefix}" in f"/{path}"
    if anchored or "/" in body:
        return fnmatch.fnmatch(path, body) or path.startswith(body + "/")
    return fnmatch.fnmatch(path.rsplit("/", 1)[-1], body)


def owners_of(rules: list[tuple[str, list[str]]], path: str) -> list[str] | None:
    """Ответственные по последнему подошедшему правилу; None — правила нет."""
    found = None
    for pattern, owners in rules:
        if matches(pattern, path):
            found = owners
    return found


def critical_files(files: list[str], project_prefix: str, guard: ModuleType) -> list[str]:
    selected = []
    for path in files:
        if path.startswith(project_prefix):
            inner = path[len(project_prefix) :]
            if any(fnmatch.fnmatch(inner, p) for p in guard.CRITICAL):
                selected.append(path)
        elif any(fnmatch.fnmatch(path, p) for p in guard.CRITICAL_REPO):
            selected.append(path)
    return selected


def check(rules: list[tuple[str, list[str]]], critical: list[str]) -> list[str]:
    problems: list[str] = []
    placeholders: set[str] = set()
    for pattern, owners in rules:
        if len(owners) < MIN_OWNERS:
            problems.append(
                f"{pattern}: ответственных {len(owners)}, нужно не меньше {MIN_OWNERS} — "
                "автор не может одобрить сам себя"
            )
        for owner in owners:
            if PLACEHOLDER.search(owner):
                placeholders.add(owner)
            elif not OWNER.match(owner):
                problems.append(f"{pattern}: {owner} — не похоже на логин GitHub")
    if placeholders:
        problems.append(
            f"заглушки вместо логинов GitHub: {', '.join(sorted(placeholders))} — "
            "подставьте логины участников"
        )
    for path in critical:
        if owners_of(rules, path) is None:
            problems.append(f"{path}: критический файл не закреплён в CODEOWNERS")
    return sorted(set(problems))


def repo_files() -> tuple[list[str], str] | None:
    git = shutil.which("git")
    if git is None:
        return None
    listed = subprocess.run(  # nosec B603  # argv фиксирован
        [git, "ls-files", "--full-name", "-z", ":/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    prefix = subprocess.run(  # nosec B603  # argv фиксирован
        [git, "rev-parse", "--show-prefix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0 or prefix.returncode != 0:
        return None
    return [f for f in listed.stdout.split("\0") if f], prefix.stdout.strip()


def main() -> int:
    if not CODEOWNERS.exists():
        print(f"Нет файла {CODEOWNERS}: критические файлы не защищены", file=sys.stderr)
        return 1
    listed = repo_files()
    if listed is None:
        print("Нужна рабочая копия git: список файлов берётся у git", file=sys.stderr)
        return 2
    files, prefix = listed
    rules = parse(CODEOWNERS.read_text(encoding="utf-8"))
    critical = critical_files(files, prefix, load_guard())
    problems = check(rules, critical)
    if not problems:
        print(
            f"CODEOWNERS: правил — {len(rules)}, все {len(critical)} критических файлов "
            f"закреплены, у каждого правила не меньше {MIN_OWNERS} ответственных"
        )
        return 0
    print(f"Нарушений в .github/CODEOWNERS: {len(problems)}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
