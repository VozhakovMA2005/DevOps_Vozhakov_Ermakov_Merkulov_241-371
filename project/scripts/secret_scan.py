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
EXAMPLE_FILES = ("env.example", "audfond.env.example")

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
    "демо-пароль",
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
ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(
        password | passwd | pwd | secret | token | api[_-]?key
        | private[_-]?key | access[_-]?key | jwt[_-]?secret
    )
    \s* [:=] \s*
    ["']([^"'\n]{6,})["']
    """
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


def gitignore_patterns() -> list[str]:
    """Образцы из .gitignore — для случая, когда git недоступен."""
    path = ROOT / ".gitignore"
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        patterns.append(line.rstrip("/"))
    return patterns


def is_ignored(relative: str, patterns: list[str]) -> bool:
    parts = relative.split("/")
    name = parts[-1]
    for pattern in patterns:
        if fnmatch(name, pattern) or fnmatch(relative, pattern):
            return True
        if pattern in parts:
            return True
    return False


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
            [git, "ls-files", "-z"],
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
    is_example = relative.endswith(EXAMPLE_FILES)
    is_sample = relative.startswith(SAMPLE_PREFIXES)

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for label, pattern, allowed_in_samples in HARD:
            if pattern.search(line) and not (is_sample and allowed_in_samples):
                findings.append(f"{relative}:{number}: {label}")

        dsn = DSN_WITH_PASSWORD.search(line)
        if (
            dsn is not None
            and not is_sample
            and not looks_substituted(line)
            and not is_placeholder(dsn.group(1))
        ):
            findings.append(
                f"{relative}:{number}: в строке подключения записан пароль"
                + (", ожидается заглушка" if is_example else "")
            )

        match = ASSIGNMENT.search(line)
        if match is None or is_sample:
            continue
        name, value = match.group(1), match.group(2)
        if looks_substituted(line) or is_placeholder(value):
            continue
        if is_example:
            findings.append(
                f"{relative}:{number}: в файле-образце настоящее значение «{name}», "
                "ожидается заглушка"
            )
        else:
            findings.append(f"{relative}:{number}: значение «{name}» записано строкой")


def scan() -> list[str]:
    findings: list[str] = []
    for path in iter_files():
        relative = path.relative_to(ROOT).as_posix()
        check_names(path, relative, findings)
        if relative in ALLOWED:
            continue
        if path.name.endswith(tuple(SKIP_SUFFIXES)):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # двоичный файл: искать в нём строки незачем
        check_content(relative, text, findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск секретов в репозитории")
    parser.add_argument("--quiet", action="store_true", help="только код возврата")
    args = parser.parse_args()

    findings = scan()
    checked = len(iter_files())
    if not findings:
        if not args.quiet:
            print(
                f"Секретов не найдено: проверено файлов в репозитории — {checked}, "
                "запрещённых файлов и записанных строкой значений нет"
            )
        return 0

    if not args.quiet:
        print(f"Найдено нарушений: {len(findings)}", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nЗапрет — ТЗ 7.2. Уберите значение в переменную окружения; "
            "исключение добавляется правкой scripts/secret_scan.py с обоснованием "
            "в запросе на слияние.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
