"""Мутационная проверка правил — пункт 5 задания.

На защите преподаватель меняет одно условие в основной логике, и тесты обязаны
это заметить. Этот сценарий делает то же самое заранее и проверяемо: он сам
портит условие, прогоняет тесты и требует, чтобы они упали. Мутация, после
которой тесты остались зелёными, называется выжившей — она означает, что
правило не покрыто проверкой.

Почему свой набор, а не готовый инструмент. Генераторы мутаций перебирают все
операторы в коде и дают тысячи мутантов, большая часть которых бессмысленна
(меняется текст сообщения, порядок полей в ответе). Прогон такого набора на
настоящей базе занимает десятки минут, а объяснять выживших мутантов приходится
по одному. Здесь набор ровно из тех условий, которые и есть правила предметной
области: D1, D2, D5, D6 и поведение импорта. Каждая мутация названа словами,
прогоняется за секунды, и видно, какой именно тест её ловит.

Запуск:

    python scripts/mutation_check.py              # весь набор
    python scripts/mutation_check.py --only D5    # одна мутация
    python scripts/mutation_check.py --list       # только перечень

Файлы правятся на диске и возвращаются в исходное состояние в любом случае,
включая прерывание по Ctrl+C.
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404  # запуск pytest: это служебный сценарий разработки
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    """Одна подмена условия и тесты, которые обязаны её поймать."""

    name: str
    rule: str
    path: str
    before: str
    after: str
    explanation: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="D5: граница вместимости сдвинута на единицу",
        rule="D5",
        path="app/services/rooms.py",
        before="    if total > capacity:",
        after="    if total > capacity + 1:",
        explanation=(
            "Нормативная вместимость превышена на одного человека — правило "
            "перестаёт срабатывать ровно на границе"
        ),
        tests=("tests/unit/test_rule_d5.py", "tests/integration/test_rooms.py"),
    ),
    Mutation(
        name="D5: округление вверх вместо округления вниз",
        rule="D5",
        path="app/models/room_type.py",
        before="        return int(area // self.area_norm)",
        after=(
            "        return int(area // self.area_norm) + "
            "(1 if area % self.area_norm else 0)"
        ),
        explanation=(
            "Площадь 62.5 при норме 2.5 даёт 25 мест, а при округлении вверх "
            "помещение «вмещает» больше людей, чем допускает норма"
        ),
        tests=("tests/unit/test_floor.py", "tests/unit/test_rule_d5.py"),
    ),
    Mutation(
        name="D6: непригодные помещения не исключаются из подбора",
        rule="D6",
        path="app/services/selection.py",
        before="        if not room.is_usable:  # D6",
        after="        if False:  # D6",
        explanation="В подбор попадают помещения, непригодные к эксплуатации",
        tests=("tests/integration/test_selection.py",),
    ),
    Mutation(
        name="D1: матрица допустимости не проверяется",
        rule="D1",
        path="app/services/selection.py",
        before="        if room.room_type_id not in allowed_type_ids:  # D1",
        after="        if room.room_type_id not in allowed_type_ids and False:  # D1",
        explanation="Дисциплину можно вести в помещении неразрешённого типа",
        tests=("tests/integration/test_selection.py",),
    ),
    Mutation(
        name="D2: нехватка мест перестаёт быть препятствием",
        rule="D2",
        path="app/services/selection.py",
        before="        if margin < 0 and not allow_overload:  # D2",
        after="        if margin < -1 and not allow_overload:  # D2",
        explanation=(
            "Группа на одного человека больше числа мест проходит без явного "
            "разрешения перегруза"
        ),
        tests=("tests/integration/test_selection.py",),
    ),
    Mutation(
        name="Импорт: неположительная площадь принимается",
        rule="Импорт",
        path="app/services/imports.py",
        before="    if number <= 0:",
        after="    if number < 0:",
        explanation="Площадь 0 проходит разбор, хотя в базе стоит CHECK area > 0",
        tests=("tests/unit/test_import_parsing.py",),
    ),
    Mutation(
        name="Импорт: сухой прогон начинает менять данные",
        rule="Импорт",
        path="app/services/imports.py",
        before=(
            "        if dry_run:\n"
            "            # Сухой прогон: проверки прошли, но в базу ничего не пишем\n"
            "            outcome.created += 1\n"
            "            continue"
        ),
        after=(
            "        if False:\n"
            "            # Сухой прогон: проверки прошли, но в базу ничего не пишем\n"
            "            outcome.created += 1\n"
            "            continue"
        ),
        explanation=(
            "Проверка файла без изменения данных перестаёт быть проверкой: "
            "ТЗ 4.1.1 требует именно сухого прогона"
        ),
        tests=("tests/integration/test_imports.py",),
    ),
    Mutation(
        name="Импорт: отказ по строке отменяет весь файл",
        rule="Импорт",
        path="app/services/imports.py",
        before=(
            "        if outcome.errors and (outcome.created or outcome.updated):\n"
            "            job.status = ImportStatus.PARTIAL"
        ),
        after=(
            "        if outcome.errors:\n"
            "            job.status = ImportStatus.FAILED  # мутация\n"
            "        elif outcome.errors and (outcome.created or outcome.updated):\n"
            "            job.status = ImportStatus.PARTIAL"
        ),
        explanation=(
            "Частичное сохранение теряет свой признак: файл с одной плохой "
            "строкой выглядит как полностью отклонённый"
        ),
        tests=("tests/integration/test_imports.py",),
    ),
)


def python_bin() -> str:
    """Тот же интерпретатор, которым запущен сценарий: версии не разъедутся."""
    return sys.executable


def run_tests(mutation: Mutation) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
        [python_bin(), "-m", "pytest", "-x", "-q", *mutation.tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def apply_mutation(mutation: Mutation) -> str:
    path = ROOT / mutation.path
    original = path.read_text(encoding="utf-8")
    if mutation.before not in original:
        raise SystemExit(
            f"Мутация «{mutation.name}» не нашла свой фрагмент в {mutation.path}.\n"
            "Код изменился — обновите набор мутаций, иначе проверка станет "
            "бессмысленной."
        )
    if original.count(mutation.before) > 1:
        raise SystemExit(
            f"Мутация «{mutation.name}» встречается в {mutation.path} несколько раз: "
            "уточните фрагмент, иначе непонятно, что именно проверяется."
        )
    path.write_text(original.replace(mutation.before, mutation.after, 1), encoding="utf-8")
    return original


def check(mutation: Mutation) -> bool:
    """True — мутация поймана тестами."""
    path = ROOT / mutation.path
    original = apply_mutation(mutation)
    try:
        result = run_tests(mutation)
    finally:
        path.write_text(original, encoding="utf-8")

    killed = result.returncode != 0
    mark = "\033[32mПОЙМАНА\033[0m" if killed else "\033[31mВЫЖИЛА \033[0m"
    print(f"  {mark}  [{mutation.rule}] {mutation.name}")
    if killed:
        failed = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("FAILED") or " failed" in line
        ]
        if failed:
            print(f"            поймал: {failed[-1].strip()}")
    else:
        print(f"            правило не покрыто: {mutation.explanation}")
    return killed


def main() -> int:
    parser = argparse.ArgumentParser(description="Мутационная проверка правил")
    parser.add_argument(
        "--only", help="прогнать мутации одного правила: D1, D2, D5, D6, Импорт"
    )
    parser.add_argument("--list", action="store_true", help="показать перечень и выйти")
    args = parser.parse_args()

    selected = [
        mutation
        for mutation in MUTATIONS
        if args.only is None or mutation.rule.lower() == args.only.lower()
    ]
    if not selected:
        print(f"Нет мутаций для правила {args.only!r}", file=sys.stderr)
        return 2

    if args.list:
        for mutation in selected:
            print(f"[{mutation.rule}] {mutation.name}")
            print(f"    {mutation.path}: {mutation.explanation}")
        return 0

    print(f"Мутационная проверка: {len(selected)} подмен условий\n")
    survived = [mutation for mutation in selected if not check(mutation)]

    print(f"\nПоймано {len(selected) - len(survived)} из {len(selected)}")
    if survived:
        print(
            "\nВыжившие мутации означают, что правило не покрыто проверкой. "
            "Добавьте тест, а не исключение.",
            file=sys.stderr,
        )
        return 1
    print("Каждая подмена условия обнаружена тестами (пункт 5 задания)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
