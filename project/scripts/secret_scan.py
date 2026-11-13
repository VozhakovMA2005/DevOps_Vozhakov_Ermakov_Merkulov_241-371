"""Поиск секретов в репозитории — ТЗ 7.2.

ТЗ прямо запрещает «размещение в репозитории секретов, файла .env, локальных
файлов окружения, резервных копий БД и артефактов сборки». Этот сценарий
проверяет запрет, а не надеется на внимательность.

Почему свой сценарий, а не готовый инструмент. Готовые ищут секреты «вообще» и
требуют файла-эталона с перечнем исключений, который со временем превращается в
список «тут мы разрешили». Здесь правила описаны в коде, читаются за минуту и
привязаны к нашему же ТЗ: запрещены файлы, запрещены значения, разрешены
только образцы с заглушками.

Что проверяется:

1. Запрещённые файлы: ``.env``, локальные файлы окружения, дампы базы,
   закрытые ключи, артефакты сборки.
2. Запрещённые значения в тексте файлов: пароли и ключи, записанные строкой.
3. Образцы (``.env.example``, ``audfond.env.example``) обязаны содержать
   заглушки, а не настоящие значения.

Запуск:

    python scripts/secret_scan.py          # проверить дерево от корня проекта
    python scripts/secret_scan.py --quiet  # только код возврата

Код возврата 1 означает находку. Пропустить находку нельзя: исключения
добавляются правкой этого файла, с обоснованием в запросе на слияние
(ТЗ 7.2 и раздел 4 CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404  # опрос git: служебный сценарий проверок
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Каталоги, в которые смотреть незачем: там либо чужой код, либо наши же
#: артефакты, которых в репозитории и так быть не должно
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "htmlcov",
        "reports",
        "backups",
        "by-task",
        "by-task-lr2",
        "by-task-lr3",
        "by-task-lr4",
    }
)

#: Двоичные и статические файлы: искать пароли в шрифтах смысла нет
SKIP_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".pdf",
        ".xlsx",
        ".zip",
        ".dump",
        ".pyc",
        ".map",
        ".min.js",
        ".min.css",
    }
)

#: Файлов с такими именами в репозитории быть не должно совсем
FORBIDDEN_NAMES = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.prod",
    ".env.docker",
    "db-passwords",
    "id_rsa",
    "id_ed25519",
    ".secrets",
    "secrets.yml",
    "secrets.yaml",
)

#: Запрещённые расширения: дампы базы и закрытые ключи
FORBIDDEN_SUFFIXES = (".dump", ".pem", ".key", ".p12", ".pfx", ".sql.gz")

#: Файлы-образцы: в них переменные есть, но значения обязаны быть заглушками
EXAMPLE_FILES = ("env.example", "audfond.env.example", "env.docker.example")

#: Слова, которые делают значение заглушкой, а не секретом
PLACEHOLDERS = (
    "change_me",
    "changeme",
    "сгенерируйте",
    "пароль_приложения",
    "пароль-приложения",
    "пароль_учений",
    "пароль_миграций",
    "вставить",
    "заполните",
    "example",
    "placeholder",
    "ваш-",
    "демо_пароль",
    # образцы в инструкциях команды: «пароль-для-sudo-2026», «пароль-миграций-2026»
    "пароль",
    "демо-пароль",
    # история команды (make secrets-history): «CHANGE_СВОЙ_КЛЮЧ» в образце
    # .env.example и ключ службы тестов «тестовый-ключ-подписи-…» в compose
    "свой_ключ",
    "тестовый-ключ",
    "xxx",
    "***",
)

#: Имя настройки -> признак того, что значение подставляется, а не записано
SAFE_VALUE_MARKERS = (
    "os.getenv",
    "os.environ",
    "${",
    "$(",
    "getenv",
    "env.",
    "config.",
    ":'",  # подстановка переменной psql: PASSWORD :'owner_password'
)

#: Подозрительные присваивания. Ищем именно «ключ = значение в кавычках»:
#: ровно так секрет и попадает в репозиторий
#: Имя может нести приставку: DB_PASSWORD, SMTP_PASSWORD, github_token. Граница
#: слова \b после подчёркивания не срабатывает, поэтому приставка описана явно
ASSIGNMENT = re.compile(
    r"""(?ix)
    (?<![a-z0-9])
    (
        (?:[a-z0-9]+[_-])*
        (?: password | passwd | pwd | secret | token | api[_-]?key
          | private[_-]?key | access[_-]?key | jwt[_-]?secret )
        (?:[_-](?:key|value|string))?
    )
    \s* [:=] \s*
    ["']([^"'\n]{6,})["']
    """
)

#: Значение без кавычек — в сценариях оболочки, файлах окружения, YAML и
#: настройках: «export DB_PASSWORD=…», «password: …». Имя — как в ASSIGNMENT
UNQUOTED = re.compile(
    r"""(?ix)
    ^\s*(?:export\s+|-\s+)?
    (
        (?:[a-z0-9]+[_-])*
        (?: password | passwd | pwd | secret | token | api[_-]?key
          | private[_-]?key | access[_-]?key | jwt[_-]?secret )
        (?:[_-](?:key|value|string))?
    )
    \s* [:=] \s*
    ([^\s"'#]{6,})
    \s*(?:\#.*)?$
    """
)

#: Значение без кавычек, похожее на выражение: вызов, индекс, обращение к полю
CODE_LIKE = re.compile(r"[()\[\]{}]|^[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)+$")

#: Файлы, где значения обычно пишут без кавычек
UNQUOTED_SUFFIXES = (
    ".sh",
    ".env",
    ".example",
    ".yml",
    ".yaml",
    ".conf",
    ".ini",
    ".cfg",
    ".service",
    ".properties",
)

#: Форматы, которые опознаются сами по себе. Третье поле — допустимо ли это в
#: тестах: образец строки подключения там нормален, а настоящий закрытый ключ
#: или токен не нужен ни в тестах, ни где-либо ещё
HARD: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("закрытый ключ", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), False),
    ("ключ доступа AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), False),
    ("токен GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), False),
)

#: Строка подключения с паролем. Пароль вынесен в группу, чтобы отличить
#: заглушку в файле-образце от настоящего значения
DSN_WITH_PASSWORD = re.compile(r"://[^\s:/@]+:([^\s:/@]{4,})@")

#: Каталоги, где образцы учётных данных — часть работы, а не утечка.
#: Жёсткие форматы из HARD тут всё равно проверяются
SAMPLE_PREFIXES = ("tests/",)

#: Исключения. Каждая строка — путь и причина, по которой находка допустима.
#: Добавлять только с обоснованием в запросе на слияние (ТЗ 7.2)
ALLOWED: dict[str, str] = {
    "scripts/secret_scan.py": "сам сценарий поиска: в нём лежат образцы искомого",
    "docs/testing.md": "в документе показаны примеры тестовых значений",
    "CONTRIBUTING.md": "в правилах приведены примеры запрещённых строк",
    "git-history/check_snapshots.py": (
        "служебный сценарий проверки снимков задач: ключ подписи нужен, чтобы "
        "поднять приложение на одноразовой базе, в бою он не используется"
    ),
}


def gitignore_patterns() -> list[tuple[str, bool]]:
    """Образцы из .gitignore — для случая, когда git недоступен.

    Второе поле — образец-исключение (строка с «!»): такой файл в
    репозиторий попадает, хотя подходит под образец выше. Без этого образцы
    .env.example и .env.docker.example считались бы игнорируемыми и не
    проверялись бы на заглушки.
    """
    path = ROOT / ".gitignore"
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        patterns.append((line.lstrip("!").rstrip("/"), negated))
    return patterns


def is_ignored(relative: str, patterns: list[tuple[str, bool]]) -> bool:
    """Как в git: последний подошедший образец решает, исключение — отменяет."""
    parts = relative.split("/")
    name = parts[-1]
    ignored = False
    for pattern, negated in patterns:
        if fnmatch(name, pattern) or fnmatch(relative, pattern) or pattern in parts:
            ignored = not negated
    return ignored


def iter_files() -> list[Path]:
    """Файлы, которые есть В РЕПОЗИТОРИИ.

    Запрет из подраздела 7.2 ТЗ относится к репозиторию, а не к рабочему
    каталогу: файл .env обязан существовать локально, иначе приложение не
    запустится, и ругаться на него — ошибка проверки. Поэтому список берётся
    у git. Если git недоступен (например, внутри образа, куда .git не
    копируется), список собирается обходом дерева с учётом .gitignore.
    """
    tracked = git_tracked_files()
    if tracked is not None:
        return tracked

    patterns = gitignore_patterns()
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if set(path.relative_to(ROOT).parts) & SKIP_DIRS:
            continue
        if is_ignored(relative, patterns):
            continue
        files.append(path)
    return files


def git_tracked_files() -> list[Path] | None:
    """Список отслеживаемых git файлов или None, если git недоступен."""
    # Полный путь, а не имя: иначе какой именно git запустится, зависит от
    # PATH. Так же уходит замечание bandit B607, и подавлять его не нужно
    git = shutil.which("git")
    if git is None:
        return None

    try:
        result = subprocess.run(  # nosec B603  # argv фиксирован, данных извне нет
            [git, "ls-files", "-z", ":/"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None

    files = []
    for name in result.stdout.decode("utf-8", "replace").split("\0"):
        if not name:
            continue
        path = ROOT / name
        if path.is_file() and not (set(Path(name).parts) & SKIP_DIRS):
            files.append(path)
    return files


def shown_path(path: Path) -> str:
    """Путь относительно проекта; файлы корня репозитория — через «../»."""
    return Path(os.path.relpath(path, ROOT)).as_posix()


def is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(word in low for word in PLACEHOLDERS)


def looks_substituted(line: str) -> bool:
    return any(marker in line for marker in SAFE_VALUE_MARKERS)


def check_names(path: Path, relative: str, findings: list[str]) -> None:
    if path.name in FORBIDDEN_NAMES:
        findings.append(f"{relative}: запрещённый файл в репозитории (ТЗ 7.2)")
    if path.name.endswith(FORBIDDEN_SUFFIXES):
        findings.append(f"{relative}: дамп базы или закрытый ключ в репозитории (ТЗ 7.2)")


def check_content(relative: str, text: str, findings: list[str]) -> None:
    for number, line in enumerate(text.splitlines(), 1):
        check_line(relative, number, line, findings)


def check_line(
    relative: str, number: int, line: str, findings: list[str], where: str = ""
) -> None:
    """Проверить одну строку файла. where — приставка к находке (коммит)."""
    is_example = relative.endswith(EXAMPLE_FILES)
    is_sample = relative.startswith(SAMPLE_PREFIXES)
    place = f"{where}{relative}:{number}"

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return

    for label, pattern, allowed_in_samples in HARD:
        if pattern.search(line) and not (is_sample and allowed_in_samples):
            findings.append(f"{place}: {label}")

    dsn = DSN_WITH_PASSWORD.search(line)
    if (
        dsn is not None
        and not is_sample
        and not looks_substituted(line)
        and not is_placeholder(dsn.group(1))
    ):
        findings.append(
            f"{place}: в строке подключения записан пароль"
            + (", ожидается заглушка" if is_example else "")
        )

    match = ASSIGNMENT.search(line)
    if match is None and relative.endswith(UNQUOTED_SUFFIXES):
        match = UNQUOTED.search(line)
        # «secret = sys.argv[1]» во встроенном Python, «token: config.token» —
        # выражение, а не значение
        if match is not None and CODE_LIKE.search(match.group(2)):
            match = None
    if match is None or is_sample:
        return
    name, value = match.group(1), match.group(2)
    # "$OWNER_PASSWORD" в сценарии оболочки — подстановка переменной, не значение
    if looks_substituted(line) or is_placeholder(value) or value.startswith("$"):
        return
    if is_example:
        findings.append(
            f"{place}: в файле-образце настоящее значение «{name}», ожидается заглушка"
        )
    else:
        findings.append(f"{place}: значение «{name}» записано строкой")


def skipped(relative: str) -> bool:
    """Файл, содержимое которого не проверяется: исключение или двоичный."""
    return (
        relative in ALLOWED
        or relative.endswith(tuple(SKIP_SUFFIXES))
        or bool(set(relative.split("/")) & SKIP_DIRS)
    )


def scan() -> list[str]:
    findings: list[str] = []
    for path in iter_files():
        relative = shown_path(path)
        check_names(path, relative, findings)
        if skipped(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # двоичный файл: искать в нём строки незачем
        check_content(relative, text, findings)
    return findings


# --------------------------------------------------------------------------- #
# Коммиты ветки
# --------------------------------------------------------------------------- #

#: Граница коммита в выводе git log: нулевые байты в тексте исходников не встречаются
COMMIT_MARK = "\0commit "
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_log(text: str) -> list[tuple[str, str, int, str]]:
    """Добавленные строки из вывода git log -p: (коммит, файл, номер строки, текст).

    Для нового файла дополнительно выдаётся запись с номером 0 и пустым текстом:
    по ней проверяется имя файла (.env, дамп, ключ).
    """
    added: list[tuple[str, str, int, str]] = []
    commit = ""
    path = ""
    new_file = False
    number = 0
    for line in text.split("\n"):
        if line.startswith(COMMIT_MARK):
            commit, path, new_file = line[len(COMMIT_MARK) :].strip(), "", False
        elif line.startswith("diff --git "):
            path, new_file = "", False
        elif line.startswith("new file mode"):
            new_file = True
        elif line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else ""
            if path and new_file:
                added.append((commit, path, 0, ""))
        elif line.startswith("@@"):
            hunk = HUNK.match(line)
            number = int(hunk.group(1)) if hunk else 0
        elif line.startswith("+") and path:
            added.append((commit, path, number, line[1:]))
            number += 1
        elif line.startswith(" ") and path:
            number += 1
    return added


def to_project(path: str, prefix: str) -> str:
    """Путь от корня репозитория -> путь относительно проекта («../» снаружи)."""
    if not prefix:
        return path
    return path[len(prefix) :] if path.startswith(prefix) else f"../{path}"


def scan_log(text: str, prefix: str = "") -> tuple[list[str], int]:
    """Находки в добавленных строках и число просмотренных коммитов."""
    findings: list[str] = []
    commits = set()
    for commit, path, number, line in parse_log(text):
        relative = to_project(path, prefix)
        commits.add(commit)
        where = f"коммит {commit[:10]}: "
        if number == 0:
            check_names(Path(relative), f"{where}{relative}", findings)
            continue
        if skipped(relative):
            continue
        check_line(relative, number, line, findings, where)
    return findings, len(commits)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("git")
    if binary is None:
        raise FileNotFoundError("git")
    return subprocess.run(  # nosec B603  # argv собран здесь, данных извне нет
        [binary, *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def log_args(*revs: str) -> list[str]:
    """Аргументы git log -p для набора коммитов: диапазон ветки или --all."""
    return [
        "log",
        "--no-merges",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        "--diff-filter=AMR",
        "--format=%x00commit %H",
        "-p",
        *revs,
        "--",
        ":/",
    ]


def scan_revs(*revs: str) -> tuple[list[str], int] | str:
    """Добавленные строки всех коммитов набора revs. Строка — текст ошибки."""
    log = git(*log_args(*revs))
    if log.returncode != 0:
        return f"git log завершился с ошибкой: {log.stderr.strip()}"
    prefix = git("rev-parse", "--show-prefix").stdout.strip()
    findings, _ = scan_log(log.stdout, prefix)
    count = git("rev-list", "--count", "--no-merges", *revs)
    return findings, int(count.stdout.strip() or 0)


def scan_history() -> tuple[list[str], int] | str:
    """Вся история: все коммиты всех веток и тегов, начиная с первого."""
    try:
        return scan_revs("--all")
    except FileNotFoundError:
        return "нужен git: проверка смотрит историю коммитов"


def scan_since(base: str) -> tuple[list[str], int] | str:
    """Все коммиты от общего предка с base до HEAD. Строка — текст ошибки."""
    try:
        merge_base = git("merge-base", base, "HEAD")
    except FileNotFoundError:
        return "нужен git: проверка смотрит историю коммитов"
    if merge_base.returncode != 0:
        return (
            f"не найден общий предок с {base}: {merge_base.stderr.strip()}. "
            "Получите основную ветку: git fetch origin main"
        )
    return scan_revs(f"{merge_base.stdout.strip()}..HEAD")


def write_report(path: Path, mode: str, checked: int, findings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"mode": mode, "checked": checked, "findings": findings},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск секретов в репозитории")
    parser.add_argument("--quiet", action="store_true", help="только код возврата")
    parser.add_argument(
        "--since",
        metavar="REF",
        help="проверить добавленные строки всех коммитов ветки от общего предка с REF",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="проверить всю историю: все коммиты всех веток и тегов",
    )
    parser.add_argument("--report", type=Path, help="записать находки в файл JSON")
    args = parser.parse_args()

    if args.all:
        result = scan_history()
        if isinstance(result, str):
            print(f"Проверка истории не выполнена: {result}", file=sys.stderr)
            return 2
        findings, checked = result
        mode, what = "вся история", f"коммитов в истории — {checked}"
    elif args.since:
        result = scan_since(args.since)
        if isinstance(result, str):
            print(f"Проверка коммитов не выполнена: {result}", file=sys.stderr)
            return 2
        findings, checked = result
        mode, what = f"коммиты после {args.since}", f"коммитов в ветке — {checked}"
    else:
        findings = scan()
        checked = len(iter_files())
        mode, what = "дерево", f"файлов в репозитории — {checked}"

    if args.report:
        write_report(args.report, mode, checked, findings)

    if not findings:
        if not args.quiet:
            print(
                f"Секретов не найдено: проверено {what}, "
                "запрещённых файлов и записанных строкой значений нет"
            )
        return 0

    if not args.quiet:
        print(f"Найдено нарушений: {len(findings)}", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        if args.all:
            print(
                "\nСекрет в истории виден всем, у кого есть доступ к репозиторию, "
                "в том числе после открытия репозитория. Значение считается раскрытым: "
                "смените его (пароль, ключ, токен) там, где оно действует. Историю "
                "main не переписывают.",
                file=sys.stderr,
            )
        elif args.since:
            print(
                "\nСекрет в истории остаётся и после удаления из файла: любой, у кого "
                "есть клон, найдёт его в git log. Значение считается раскрытым — его "
                "надо сменить, а коммит переписать до слияния (ветка ещё не в main).",
                file=sys.stderr,
            )
        print(
            "\nЗапрет — ТЗ 7.2. Уберите значение в переменную окружения; "
            "исключение добавляется правкой scripts/secret_scan.py с обоснованием "
            "в запросе на слияние.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
