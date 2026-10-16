"""Запрет на исключения без обоснования — пункт 14 задания, ТЗ 7.2.

ТЗ запрещает «удаление или пропуск тестов, отключение анализаторов, снижение
порогов качества и добавление исключений без обоснования в запросе на слияние».
Словами это уже записано в CONTRIBUTING.md. Этот сценарий делает запрет
проверяемым: нельзя добавить подавление и забыть объяснить, зачем.

Проверяется три вещи.

1. **Подавления анализаторов** (``# noqa``, ``# type: ignore``, ``# nosec``,
   ``# pragma: no cover``) обязаны нести рядом причину по-русски. Само
   подавление не запрещено: иногда анализатор ошибается. Запрещено молчаливое
   подавление, потому что через месяц никто не вспомнит, почему оно там.

2. **Пропуск тестов** (``@pytest.mark.skip``, ``xfail``, ``pytest.skip(...)``)
   обязан нести текст причины.

3. **Порог покрытия** в pyproject.toml не ниже значения из ТЗ 7.1.
   Здесь он захардкожен специально: чтобы снизить порог, придётся править и
   настройку, и эту проверку — то есть сделать это заметно в запросе на слияние.

Запуск:

    python scripts/waiver_check.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Порог из ТЗ 7.1. Снижение — отдельное решение, а не правка одной цифры
REQUIRED_COVERAGE = 70

SCAN_DIRS = ("app", "scripts", "tests", "migrations")

#: Подавления анализаторов, требующие причины
WAIVERS = (
    re.compile(r"#\s*noqa\b"),
    re.compile(r"#\s*type:\s*ignore"),
    re.compile(r"#\s*nosec\b"),
    re.compile(r"#\s*pragma:\s*no cover"),
)

#: Причина: после подавления идёт тире или второй знак решётки и текст.
#: Десяти символов хватает, чтобы отсечь «ok» и «надо», но не заставить
#: писать сочинение
REASON = re.compile(r"(?:—|--|\s-\s|#)\s*\S[^\n]{9,}")

SKIP_MARKS = re.compile(r"@pytest\.mark\.(skip|skipif|xfail)")
SKIP_CALL = re.compile(r"\bpytest\.skip\(")
REASON_ARG = re.compile(r"(reason\s*=\s*|pytest\.skip\(\s*)[\"'f]")


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for name in SCAN_DIRS:
        directory = ROOT / name
        if not directory.exists():
            continue
        files += [
            path for path in sorted(directory.rglob("*.py")) if "__pycache__" not in path.parts
        ]
    return files


def check_waivers(path: Path, findings: list[str]) -> None:
    relative = path.relative_to(ROOT).as_posix()
    if relative == "scripts/waiver_check.py":
        return  # в самом сценарии лежат образцы искомого

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for waiver in WAIVERS:
            match = waiver.search(line)
            if match is None:
                continue
            tail = line[match.end() :]
            # после кода правила в квадратных скобках причина тоже считается
            tail = re.sub(r"^\s*\[[^\]]*\]", "", tail)
            if REASON.search(tail) is None:
                findings.append(
                    f"{relative}:{number}: подавление без обоснования — "
                    f"{match.group(0).strip()}"
                )

        if (SKIP_MARKS.search(line) or SKIP_CALL.search(line)) and not REASON_ARG.search(line):
            findings.append(f"{relative}:{number}: пропуск теста без указания причины")


def check_coverage_threshold(findings: list[str]) -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    actual = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if actual is None:
        findings.append("pyproject.toml: не задан порог покрытия fail_under (ТЗ 7.1)")
    elif actual < REQUIRED_COVERAGE:
        findings.append(
            f"pyproject.toml: порог покрытия {actual}% ниже требуемых "
            f"{REQUIRED_COVERAGE}% (ТЗ 7.1)"
        )


def check_no_cov_flags(findings: list[str]) -> None:
    """В Makefile не должно быть отключения покрытия или тестов «на время»."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for flag in ("--no-cov", "--exitfirst --no-header -q --co", "-k 'not '"):
        if flag in makefile:
            findings.append(f"Makefile: обнаружено ослабление проверок — {flag}")


def main() -> int:
    findings: list[str] = []
    for path in iter_python_files():
        check_waivers(path, findings)
    check_coverage_threshold(findings)
    check_no_cov_flags(findings)

    if not findings:
        print(
            "Исключений без обоснования нет, порог покрытия "
            f"не ниже {REQUIRED_COVERAGE}% (ТЗ 7.1, 7.2)"
        )
        return 0

    print(f"Нарушений: {len(findings)}", file=sys.stderr)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(
        "\nЗапрет — пункт 14 задания и ТЗ 7.2. Подавление допустимо, "
        "молчаливое подавление — нет: допишите причину в той же строке.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
