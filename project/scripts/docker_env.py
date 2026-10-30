"""Создать .env.docker для контейнерного окружения — ЛР4, пункт 4.

Берёт образец .env.docker.example и подставляет вместо заглушек случайные
значения: пароль базы, ключ подписи токенов, пароль администратора и пароль
демонстрационных учёток. Готовый файл получает права 600.

Существующий файл не перезаписывается: в нём пароль базы, с которым уже
создан том с данными, и новый пароль к старому тому не подойдёт.

    python3 scripts/docker_env.py
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / ".env.docker.example"
TARGET = ROOT / ".env.docker"

#: Переменная -> длина случайного значения в байтах
GENERATED = {
    "POSTGRES_PASSWORD": 24,
    "JWT_SECRET": 48,
    "ADMIN_PASSWORD": 12,
    "SEED_PASSWORD": 12,
}


def main() -> int:
    if TARGET.exists():
        print(f"{TARGET.name} уже существует, файл не изменён.")
        print("Повторная генерация требует удаления тома базы (make clean): пароль базы")
        print("задаётся при создании тома.")
        return 0
    if not SAMPLE.exists():
        print(f"Нет образца {SAMPLE.name}", file=sys.stderr)
        return 1

    lines = []
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0].strip()
        if name in GENERATED and not line.lstrip().startswith("#"):
            line = f"{name}={secrets.token_urlsafe(GENERATED[name])}"
        lines.append(line)

    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    TARGET.chmod(0o600)
    print(f"Создан {TARGET.name} (права 600). Сгенерированы: {', '.join(GENERATED)}.")
    print(f"Учётные данные администратора: ADMIN_USERNAME и ADMIN_PASSWORD в {TARGET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
