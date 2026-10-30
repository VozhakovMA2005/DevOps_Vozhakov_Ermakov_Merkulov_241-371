#!/usr/bin/env bash
# Единый сценарий первоначальной настройки проекта — пункт 1 задания.
#
# Делает всё, что нужно, чтобы с чистой машины дойти до работающего
# приложения, и ничего сверх этого:
#
#   проверяет версию Python
#   создаёт виртуальное окружение и ставит зависимости по закреплённым версиям
#   создаёт .env из образца и подставляет в него сгенерированный ключ подписи
#   накатывает миграции, если база доступна
#   подсказывает следующий шаг
#
# Повторный запуск безопасен: готовое не переделывается, .env не перезаписывается.
#
#   bash scripts/setup.sh              обычная настройка
#   bash scripts/setup.sh --no-db      без обращения к базе

. "$(dirname "$0")/lib.sh"

cd "$ROOT"

SKIP_DB=0
[ "${1:-}" = "--no-db" ] && SKIP_DB=1

MIN_PYTHON="3.12"

step "Python"
require_command python3 "Поставьте Python $MIN_PYTHON или новее."
PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$(printf '%s\n%s\n' "$MIN_PYTHON" "$PYTHON_VERSION" | sort -V | head -1)" != "$MIN_PYTHON" ]; then
    die "Нужен Python $MIN_PYTHON или новее, найден $PYTHON_VERSION"
fi
ok "Python $PYTHON_VERSION"

step "Виртуальное окружение"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
    ok "создано $VENV"
else
    info "уже есть, переиспользуется"
fi

step "Зависимости по закреплённым версиям"
# Закреплённые версии — требование ТЗ 7.1 и пункта 2 задания. Проверять надо
# именно ими: более свежая библиотека прощает то, на чём упадёт развёртывание
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements-dev.txt
ok "установлены из requirements-dev.txt"

step "Файл настроек"
if [ -f .env ]; then
    info ".env уже есть, не переписываю"
else
    cp .env.example .env
    SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    # Ключ подписи генерируется, а не берётся из образца: иначе он одинаковый
    # у всех, кто склонировал репозиторий (ТЗ 4.6)
    "$VENV/bin/python" - "$SECRET" <<'PY'
import pathlib
import sys

secret = sys.argv[1]
path = pathlib.Path(".env")
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("JWT_SECRET="):
        line = f"JWT_SECRET={secret}"
    lines.append(line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
    chmod 600 .env
    ok "создан .env, ключ подписи сгенерирован"
    warn "впишите в .env адрес базы: DATABASE_URL"
fi

if [ "$SKIP_DB" = "1" ]; then
    step "База данных"
    info "пропущено по ключу --no-db"
else
    step "База данных"
    load_env
    parse_database_url
    if ! command -v pg_isready >/dev/null 2>&1; then
        warn "нет pg_isready, доступность базы не проверяю"
    elif wait_for_database 10; then
        ok "база $PGDATABASE на $PGHOST:$PGPORT отвечает"
        info "накатываю миграции"
        "$VENV/bin/python" -m alembic upgrade head
        ok "схема на последней ревизии"
    else
        warn "база $PGHOST:$PGPORT не отвечает — миграции не накатывал"
        info "поднимите базу и выполните: .venv/bin/python -m alembic upgrade head"
    fi
fi

step "Готово"
info "дальше по порядку:"
info "  1) первый администратор:  make create-admin"
info "  2) запуск:                make run"
info "  3) проверки:              make verify        (в контейнерах)"
info "                            make verify-local  (без контейнеров)"
