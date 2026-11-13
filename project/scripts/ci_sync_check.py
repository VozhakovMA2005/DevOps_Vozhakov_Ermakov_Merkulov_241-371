"""Конвейер на сервере и make ci совпадают — ЛР5, пункт 4; ТЗ 7.1.

Команда make ci-sync. Сравнивает .github/workflows/ci.yml со стадиями
scripts/ci_local.sh и проверяет:

    1. проверки ТЗ 7.1 есть и идут цепочкой в порядке ТЗ:
       lint → types → sast → test → test-int → migrate-check →
       schema-check → secrets-scan → deps-check;
    2. у каждой стадии make ci есть задача CI с тем же именем, и обе
       вызывают одни и те же цели make — и наоборот;
    3. итоговая задача ci-gate ждёт все стадии, публикация ждёт ci-gate;
    4. ни одна задача не помечена continue-on-error, ошибка make не
       подавлена;
    5. используются только действия GitHub (actions/*) и действия
       репозитория, с закреплённой версией.

Так требование «локальные и серверные проверки совпадают» проверяется, а
не только записано: добавить проверку в CI, забыв про Makefile, или
наоборот, не получится.

Только стандартная библиотека: файл CI разбирается построчно, этого
хватает для его однородной структуры.

    python3 scripts/ci_sync_check.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Порядок проверок из ТЗ 7.1
TZ_ORDER = (
    "lint",
    "types",
    "sast",
    "test",
    "test-int",
    "migrate-check",
    "schema-check",
    "secrets-scan",
    "deps-check",
)
#: Служебные задачи CI без стадии в make ci
SERVICE_JOBS = {"config", "ci-gate", "publish", "publish-local"}
#: Вспомогательные цели make: готовят окружение, а не проверяют
HELPER_TARGETS = {"docker-env", "push"}
#: Действия GitHub с закреплённой основной версией или полным SHA коммита,
#: и действия самого репозитория
ALLOWED_ACTION = re.compile(
    r"^(actions/[\w.-]+@(v\d+|[0-9a-f]{40})|\./\.github/actions/[\w./-]+)$"
)
#: Подавление ошибки команды: «|| true», «|| :», «|| exit 0», «; exit 0», «; true»
SUPPRESSED = re.compile(r"\|\|\s*(true|:|exit\s+0)\b|;\s*(true|exit\s+0)\b")


@dataclass
class Job:
    name: str
    needs: list[str] = field(default_factory=list)
    targets: set[str] = field(default_factory=set)
    uses: list[str] = field(default_factory=list)
    continue_on_error: bool = False
    suppressed: bool = False
    disabled_steps: int = 0


def make_targets(command: str) -> set[str]:
    """Цели из строки «make a b VAR=x»: слова без = и без ключей."""
    words = command.split()
    return {w for w in words[1:] if "=" not in w and not w.startswith("-")}


def parse_workflow(text: str) -> dict[str, Job]:
    jobs: dict[str, Job] = {}
    current: Job | None = None
    in_jobs = False
    in_needs_block = False
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line:
            continue
        if line == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        job = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if job:
            current = jobs.setdefault(job.group(1), Job(job.group(1)))
            in_needs_block = False
            continue
        if current is None:
            continue
        if in_needs_block:
            item = re.match(r"^\s{6}-\s+([A-Za-z0-9_-]+)\s*$", line)
            if item:
                current.needs.append(item.group(1))
                continue
            in_needs_block = False
        needs = re.match(r"^    needs:\s*(.*)$", line)
        if needs:
            value = needs.group(1).strip()
            if not value:
                in_needs_block = True
            else:
                current.needs += [v.strip() for v in value.strip("[]").split(",") if v.strip()]
            continue
        if re.match(r"^\s+continue-on-error:\s*(true|\$\{\{)", line):
            current.continue_on_error = True
        # Шаг или задача, выключенные условием, которое всегда ложно
        if re.match(r"^\s+(?:-\s+)?if:\s*(false|\$\{\{\s*false\s*\}\}|0)\s*$", line):
            current.disabled_steps += 1
        uses = re.match(r"^\s+(?:-\s+)?uses:\s*(\S+)", line)
        if uses:
            current.uses.append(uses.group(1))
        run = re.match(r"^\s+(?:-\s+)?run:\s*(make\s.*)$", line)
        if run:
            command = run.group(1)
            if SUPPRESSED.search(command):
                current.suppressed = True
            current.targets |= make_targets(command) - HELPER_TARGETS
    return jobs


def parse_stages(text: str) -> dict[str, set[str]]:
    """Стадии make ci: имя (до « — ») -> цели make."""
    stages: dict[str, set[str]] = {}
    block = re.search(r"^STAGES=\(\n(.*?)^\)", text, re.MULTILINE | re.DOTALL)
    if block is None:
        return stages
    for entry in re.findall(r'^\s*"([^"]+)"', block.group(1), re.MULTILINE):
        title, _, targets = entry.partition("|")
        name = title.split(" — ", 1)[0].strip()
        stages[name] = set(targets.split()) - HELPER_TARGETS
    return stages


def check(jobs: dict[str, Job], stages: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []

    previous = None
    for name in TZ_ORDER:
        if name not in jobs:
            problems.append(f"нет задачи CI «{name}» из ТЗ 7.1")
        elif previous is not None and previous not in jobs[name].needs:
            problems.append(
                f"задача «{name}» должна идти после «{previous}» (needs), как в ТЗ 7.1"
            )
        previous = name

    for name, targets in stages.items():
        job = jobs.get(name)
        if job is None:
            problems.append(f"стадия make ci «{name}» отсутствует в CI")
        elif job.targets != targets:
            problems.append(
                f"«{name}»: в make ci цели {sorted(targets)}, в CI — {sorted(job.targets)}"
            )
    for name in jobs:
        if name not in SERVICE_JOBS and name not in stages:
            problems.append(f"задача CI «{name}» отсутствует в make ci (scripts/ci_local.sh)")

    gate = jobs.get("ci-gate")
    if gate is None:
        problems.append("нет итоговой задачи ci-gate")
    else:
        missing = [n for n in jobs if n not in SERVICE_JOBS and n not in gate.needs]
        if missing:
            problems.append(f"ci-gate не ждёт стадии: {', '.join(missing)}")
    for name in ("publish", "publish-local"):
        if name in jobs and "ci-gate" not in jobs[name].needs:
            problems.append(
                f"«{name}» должна ждать ci-gate: публикация только после всех стадий"
            )

    for name, job in jobs.items():
        if job.continue_on_error:
            problems.append(
                f"«{name}»: continue-on-error — сбой задачи не остановил бы конвейер"
            )
        if job.suppressed:
            problems.append(f"«{name}»: ошибка make подавлена (|| true, exit 0)")
        if job.disabled_steps:
            problems.append(f"«{name}»: шаг или задача выключены условием if: false")
        for action in job.uses:
            if not ALLOWED_ACTION.match(action):
                problems.append(
                    f"«{name}»: действие {action} — разрешены только actions/*@vN от GitHub "
                    "и действия репозитория"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Конвейер CI и make ci совпадают")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=ROOT,
        help="каталог project/ проверяемого дерева (guard-main проверяет им файлы запроса)",
    )
    args = parser.parse_args()
    project = args.project_dir.resolve()
    workflow = project.parent / ".github" / "workflows" / "ci.yml"
    ci_local = project / "scripts" / "ci_local.sh"
    if not workflow.exists():
        print(f"Нет файла конвейера {workflow}", file=sys.stderr)
        return 1
    jobs = parse_workflow(workflow.read_text(encoding="utf-8"))
    stages = parse_stages(ci_local.read_text(encoding="utf-8"))
    problems = check(jobs, stages)
    if not problems:
        print(
            f"Конвейер CI и make ci совпадают: стадий — {len(stages)}, порядок ТЗ 7.1 "
            "соблюдён, публикация только после ci-gate"
        )
        return 0
    print(f"Расхождений: {len(problems)}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(
        "\nНовая проверка добавляется в Makefile и в обе стороны сразу: "
        "scripts/ci_local.sh и .github/workflows/ci.yml.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
