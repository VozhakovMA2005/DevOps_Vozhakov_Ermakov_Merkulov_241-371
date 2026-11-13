"""Проверка зависимостей на известные уязвимости — ЛР5, пункт 12.

Команда make deps-check. Проверяются lock-файлы, из которых собирается образ
и окружение проверок: requirements.lock и requirements-dev.lock. Проверка идёт
по закреплённым версиям с контрольными суммами, ничего не устанавливается.

Инструмент — pip-audit, версия закреплена в requirements-dev.txt. Сведения об
уязвимостях берутся из базы PyPI (она же база OSV для пакетов Python).

Коды возврата:

    0  уязвимостей нет
    1  найдены уязвимости
    2  проверка не выполнена: база уязвимостей недоступна или ответ не разобран.
       Отсутствие данных не означает отсутствия уязвимостей, поэтому это тоже
       отказ

Исключения перечислены в словаре ALLOWED: идентификатор уязвимости и причина,
по которой она не касается проекта. Добавляются только с обоснованием в
запросе на слияние (ТЗ 7.2). Ключей для пропуска проверки нет.

Запуск:

    python scripts/deps_check.py
    python scripts/deps_check.py --report reports/pip-audit.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404  # запуск pip-audit: служебный сценарий проверок
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILES = ("requirements.lock", "requirements-dev.lock")
DEFAULT_REPORT = ROOT / "reports" / "pip-audit.json"

#: Принятые исключения: идентификатор -> причина. Пусто — исключений нет
ALLOWED: dict[str, str] = {}


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    vuln_id: str
    fixed_in: tuple[str, ...]
    aliases: tuple[str, ...]

    def describe(self) -> str:
        fix = (
            f"исправлено в {', '.join(self.fixed_in)}" if self.fixed_in else "исправления нет"
        )
        alias = f" ({', '.join(self.aliases)})" if self.aliases else ""
        return f"{self.package} {self.version}: {self.vuln_id}{alias}; {fix}"


def parse_report(data: dict[str, Any]) -> tuple[list[Finding], list[str]]:
    """Находки и пропущенные пакеты из отчёта pip-audit в формате JSON.

    Один и тот же пакет встречается в обоих lock-файлах, поэтому находки
    сводятся по паре «пакет, идентификатор».
    """
    findings: dict[tuple[str, str], Finding] = {}
    skipped: list[str] = []
    for dep in data.get("dependencies", []):
        name = str(dep.get("name", "?"))
        version = str(dep.get("version", "?"))
        if dep.get("skip_reason"):
            skipped.append(f"{name}: {dep['skip_reason']}")
            continue
        for vuln in dep.get("vulns", []):
            vuln_id = str(vuln.get("id", "?"))
            findings.setdefault(
                (name, vuln_id),
                Finding(
                    package=name,
                    version=version,
                    vuln_id=vuln_id,
                    fixed_in=tuple(vuln.get("fix_versions") or ()),
                    aliases=tuple(vuln.get("aliases") or ()),
                ),
            )
    ordered = sorted(findings.values(), key=lambda f: (f.package, f.vuln_id))
    return ordered, sorted(set(skipped))


def split_allowed(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Разделить находки на принятые исключения и нарушения.

    Исключение действует и по основному идентификатору, и по псевдониму
    (CVE, GHSA): база может сменить основной идентификатор записи.
    """
    allowed: list[Finding] = []
    blocking: list[Finding] = []
    for finding in findings:
        (allowed if reason_for(finding) else blocking).append(finding)
    return allowed, blocking


def reason_for(finding: Finding) -> str:
    """Причина исключения или пустая строка, если исключения нет."""
    for vuln_id in (finding.vuln_id, *finding.aliases):
        if vuln_id in ALLOWED:
            return ALLOWED[vuln_id]
    return ""


def shown(path: Path) -> str:
    """Путь для сообщения: относительно проекта, если он внутри него."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def run_pip_audit(report: Path) -> int:
    pip_audit = shutil.which("pip-audit")
    if pip_audit is None:
        print(
            "Нет pip-audit. Он закреплён в requirements-dev.txt: "
            "make setup (без контейнеров) или make build (образ проверок)",
            file=sys.stderr,
        )
        return 2

    command = [pip_audit, "--progress-spinner", "off", "--format", "json"]
    command += ["--output", str(report)]
    for name in LOCK_FILES:
        command += ["--requirement", str(ROOT / name)]
    # Версии и контрольные суммы уже закреплены в lock-файлах: зависимости
    # не разрешаются заново и ничего не устанавливается
    command += ["--require-hashes", "--disable-pip"]
    command += ["--vulnerability-service", "pypi", "--timeout", "30"]
    # Кэш — во временном каталоге: у пользователя образа нет домашнего каталога
    command += ["--cache-dir", str(Path(tempfile.gettempdir()) / "audfond-pip-audit")]
    for vuln_id in sorted(ALLOWED):
        command += ["--ignore-vuln", vuln_id]

    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    result = subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if not report.exists():
        print("Проверка не выполнена: pip-audit не сформировал отчёт.", file=sys.stderr)
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        for line in tail:
            print(f"  {line}", file=sys.stderr)
        print(
            "Нужен доступ к pypi.org. Отсутствие данных об уязвимостях — не то же "
            "самое, что отсутствие уязвимостей, поэтому проверка считается не пройденной.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка зависимостей на уязвимости")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="файл отчёта JSON")
    args = parser.parse_args()

    if run_pip_audit(args.report) != 0:
        return 2

    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Отчёт pip-audit не разобран: {exc}", file=sys.stderr)
        return 2

    findings, skipped = parse_report(data)
    allowed, blocking = split_allowed(findings)
    checked = len({dep.get("name") for dep in data.get("dependencies", [])})

    for finding in allowed:
        print(f"  исключение  {finding.describe()} — {reason_for(finding)}")
    for item in skipped:
        print(f"  не проверен {item}")

    if not blocking:
        print(
            f"Известных уязвимостей нет: проверено пакетов — {checked} "
            f"({', '.join(LOCK_FILES)}). Отчёт: {shown(args.report)}"
        )
        return 0

    print(f"Найдено уязвимостей: {len(blocking)}", file=sys.stderr)
    for finding in blocking:
        print(f"  {finding.describe()}", file=sys.stderr)
    print(
        "\nОбновите пакет до исправленной версии в requirements*.txt и пересоберите "
        "lock-файлы (make lock). Если уязвимость не касается проекта — исключение "
        "в словаре ALLOWED этого сценария с причиной и обоснованием в запросе на "
        f"слияние (ТЗ 7.2). Отчёт: {shown(args.report)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
