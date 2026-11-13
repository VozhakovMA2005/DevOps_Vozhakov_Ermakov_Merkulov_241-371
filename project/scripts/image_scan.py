"""Анализ контейнерного образа на уязвимости — ЛР5, пункт 12.

Команда make image-scan. Проверяется образ приложения — тот, что публикуется
и работает в бою. Ищутся известные уязвимости в пакетах системы (Debian) и в
пакетах Python внутри образа.

Инструмент — Trivy в контейнере. Версия закреплена точно (после компрометации
выпусков Trivy в марте 2026 плавающий тег у инструмента безопасности особенно
опасен). Сканер не получает доступа к docker.sock: образ передаётся ему файлом
(docker image save), только для чтения, и работает он не от root.

Порог: уязвимости уровней HIGH и CRITICAL, для которых выпущено исправление.
Уязвимость без исправления устранить обновлением нельзя, она не блокирует,
но видна в отчёте reports/trivy.json, если запустить с --all.

Исключения — файл .trivyignore.yaml. У каждого обязательны причина (statement)
и срок пересмотра (expired_at): бессрочное исключение превращается в забытое.
Просроченное исключение — отказ.

Коды возврата:

    0  уязвимостей выше порога нет
    1  найдены уязвимости или нарушен порядок исключений
    2  проверка не выполнена: нет образа, Docker или базы уязвимостей

Только стандартная библиотека: запускается на машине без окружения проекта.

    python3 scripts/image_scan.py
    python3 scripts/image_scan.py --image audfond:0.4.0 --report reports/trivy.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess  # nosec B404  # запуск docker: служебный сценарий проверок
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_IMAGE = "audfond:0.4.0"
TRIVY_IMAGE = "aquasec/trivy:0.72.0"
IGNORE_FILE = ROOT / ".trivyignore.yaml"
DEFAULT_REPORT = ROOT / "reports" / "trivy.json"
#: Кэш базы уязвимостей между запусками: без него каждый запуск качает базу заново
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "audfond-trivy"
SEVERITY = "HIGH,CRITICAL"
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}


@dataclass(frozen=True)
class Vulnerability:
    vuln_id: str
    package: str
    installed: str
    fixed: str
    severity: str
    target: str

    def describe(self) -> str:
        fix = f"исправлено в {self.fixed}" if self.fixed else "исправления нет"
        return (
            f"{self.severity:<8} {self.vuln_id:<20} {self.package} {self.installed}; "
            f"{fix} ({self.target})"
        )


@dataclass(frozen=True)
class IgnoreEntry:
    vuln_id: str
    statement: str
    expired_at: str


# --------------------------------------------------------------------------- #
# Исключения
# --------------------------------------------------------------------------- #


def parse_ignore_file(text: str) -> list[IgnoreEntry]:
    """Разбор .trivyignore.yaml без сторонних библиотек.

    Поддерживается ровно то подмножество YAML, что нужно файлу исключений:
    список vulnerabilities из записей с ключами id, statement, expired_at,
    paths, purls. Значения в кавычках и без.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+id:\s*(.+)$", line)
        if item:
            current = {"id": unquote(item.group(1))}
            entries.append(current)
            continue
        field = re.match(r"^\s+(statement|expired_at):\s*(.*)$", line)
        if field and current is not None:
            current[field.group(1)] = unquote(field.group(2))
    return [
        IgnoreEntry(e["id"], e.get("statement", ""), e.get("expired_at", "")) for e in entries
    ]


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def check_ignore_entries(entries: list[IgnoreEntry], today: dt.date) -> list[str]:
    """Нарушения порядка исключений: нет причины, нет срока, срок истёк."""
    problems = []
    for entry in entries:
        if len(entry.statement.strip()) < 10:
            problems.append(
                f"{entry.vuln_id}: нет причины (statement) — исключение без обоснования"
            )
        if not entry.expired_at:
            problems.append(f"{entry.vuln_id}: нет срока пересмотра (expired_at)")
            continue
        try:
            expires = dt.date.fromisoformat(entry.expired_at)
        except ValueError:
            problems.append(
                f"{entry.vuln_id}: срок {entry.expired_at!r} не в формате ГГГГ-ММ-ДД"
            )
            continue
        if expires < today:
            problems.append(f"{entry.vuln_id}: срок исключения истёк {expires} — пересмотрите")
    return problems


# --------------------------------------------------------------------------- #
# Отчёт Trivy
# --------------------------------------------------------------------------- #


def parse_report(data: dict[str, Any]) -> list[Vulnerability]:
    found: dict[tuple[str, str, str], Vulnerability] = {}
    for result in data.get("Results") or []:
        target = str(result.get("Target", "?"))
        for vuln in result.get("Vulnerabilities") or []:
            item = Vulnerability(
                vuln_id=str(vuln.get("VulnerabilityID", "?")),
                package=str(vuln.get("PkgName", "?")),
                installed=str(vuln.get("InstalledVersion", "?")),
                fixed=str(vuln.get("FixedVersion") or ""),
                severity=str(vuln.get("Severity", "UNKNOWN")),
                target=target,
            )
            found.setdefault((item.vuln_id, item.package, item.installed), item)
    return sorted(
        found.values(),
        key=lambda v: (SEVERITY_ORDER.get(v.severity, 9), v.package, v.vuln_id),
    )


def blocking(vulns: list[Vulnerability], severities: set[str]) -> list[Vulnerability]:
    """Блокирующие: уровень не ниже порога и есть исправление."""
    return [v for v in vulns if v.severity in severities and v.fixed]


# --------------------------------------------------------------------------- #
# Запуск
# --------------------------------------------------------------------------- #


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("docker")
    if binary is None:
        raise FileNotFoundError("docker")
    return subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
        [binary, *args], capture_output=True, text=True, check=False
    )


def run_trivy(image: str, report: Path, show_all: bool) -> int:
    """Сохранить образ в файл и проверить его Trivy. 0 — отчёт получен."""
    try:
        inspect = docker("image", "inspect", image)
    except FileNotFoundError:
        print("Нужен Docker: сканер работает в контейнере", file=sys.stderr)
        return 2
    if inspect.returncode != 0:
        print(f"Нет образа {image}: сначала make build", file=sys.stderr)
        return 2

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="audfond-scan-") as tmp:
        archive = Path(tmp) / "image.tar"
        saved = docker("image", "save", image, "-o", str(archive))
        if saved.returncode != 0:
            print(f"Не удалось сохранить образ: {saved.stderr.strip()}", file=sys.stderr)
            return 2

        command = [
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{CACHE_DIR}:/cache",
            "-v",
            f"{tmp}:/scan:ro",
            "-v",
            f"{report.parent.resolve()}:/reports",
            "-v",
            f"{IGNORE_FILE}:/policy/trivyignore.yaml:ro",
        ]
        # Зеркала базы уязвимостей и прочие настройки Trivy — переменными TRIVY_*
        for name in sorted(os.environ):
            if name.startswith("TRIVY_"):
                command += ["-e", name]
        command += [
            TRIVY_IMAGE,
            "image",
            "--input",
            "/scan/image.tar",
            "--cache-dir",
            "/cache",
            "--scanners",
            "vuln",
            "--ignorefile",
            "/policy/trivyignore.yaml",
            "--format",
            "json",
            "--output",
            f"/reports/{report.name}",
            "--timeout",
            "15m",
            "--quiet",
        ]
        if not show_all:
            command += ["--severity", SEVERITY, "--ignore-unfixed"]
        result = docker(*command)

    if result.returncode != 0 or not report.exists():
        print("Анализ образа не выполнен: Trivy завершился с ошибкой.", file=sys.stderr)
        for line in (result.stderr or result.stdout).strip().splitlines()[-8:]:
            print(f"  {line}", file=sys.stderr)
        print(
            "Trivy загружает базу уязвимостей с mirror.gcr.io или ghcr.io; зеркало "
            "задаётся переменной TRIVY_DB_REPOSITORY. Отсутствие данных — не "
            "отсутствие уязвимостей, поэтому проверка считается не пройденной.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Анализ образа на уязвимости (Trivy)")
    parser.add_argument("--image", default=os.environ.get("IMAGE", APP_IMAGE))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--all", action="store_true", help="в отчёт — все уровни и без исправлений"
    )
    args = parser.parse_args()

    if not IGNORE_FILE.exists():
        print(f"Нет файла исключений {IGNORE_FILE.name}", file=sys.stderr)
        return 1
    entries = parse_ignore_file(IGNORE_FILE.read_text(encoding="utf-8"))
    problems = check_ignore_entries(entries, dt.date.today())
    if problems:
        print(f"Нарушен порядок исключений в {IGNORE_FILE.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    code = run_trivy(args.image, args.report, args.all)
    if code != 0:
        return code

    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Отчёт Trivy не разобран: {exc}", file=sys.stderr)
        return 2

    vulns = parse_report(data)
    stop = blocking(vulns, set(SEVERITY.split(",")))
    for entry in entries:
        print(f"  исключение  {entry.vuln_id} до {entry.expired_at} — {entry.statement}")

    if not stop:
        print(
            f"Образ {args.image}: уязвимостей уровней {SEVERITY} с выпущенным "
            f"исправлением нет. Сканер {TRIVY_IMAGE}, отчёт: reports/{args.report.name}"
        )
        return 0

    print(f"Образ {args.image}: найдено уязвимостей — {len(stop)}", file=sys.stderr)
    for vuln in stop:
        print(f"  {vuln.describe()}", file=sys.stderr)
    print(
        "\nОбычно это устаревший базовый образ или пакет: обновите ARG PYTHON_IMAGE в "
        "docker/Dockerfile до свежего выпуска или пакет в requirements*.txt, затем "
        "make build и снова make image-scan. Исключение — запись в .trivyignore.yaml "
        "с причиной и сроком, с обоснованием в запросе на слияние (ТЗ 7.2).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
