#!/usr/bin/env bash
# Запуск команды проверочного контура в локальном окружении проекта.
#
# ТЗ 7.1 требует, чтобы в CI выполнялись те же команды, что и локально.
# Контур один, а запускать его можно двумя способами: в контейнерах и без них.
# Этот сценарий — вторая половина: он подставляет окружение и уходит в exec,
# поэтому команда выполняется ровно та же, что в контейнере.
#
# Что делает:
#   переходит в корень проекта
#   читает .env, если он есть
#   ставит .venv/bin в начало PATH
#   подставляет адрес роли, которой можно создавать базы (нужен тестам)
#
#   bash scripts/run.sh pytest -q
#   bash scripts/run.sh python scripts/secret_scan.py
#
# Напрямую звать не обязательно: Makefile делает это сам, когда докера нет.

. "$(dirname "$0")/lib.sh"

cd "$ROOT"

[ -x "$VENV/bin/python" ] || die "Нет окружения $VENV. Выполните: make setup"
[ $# -gt 0 ] || die "Укажите команду: bash scripts/run.sh pytest -q"

# Настройки приложения
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# VENV в lib.sh уже абсолютный: складывать его с ROOT нельзя, иначе путь
# получится несуществующим, PATH провалится к системным версиям, и проверки
# пойдут не теми версиями, что закреплены (ТЗ 7.1)
export PATH="$VENV/bin:$PATH"

# Набору тестов нужна роль, которой можно создавать базы: на каждый прогон
# заводится своя база. Роль приложения этого не может и не должна (ТЗ 4.4),
# поэтому адрес берётся из роли учений, если он не задан явно
if [ -z "${ADMIN_DATABASE_URL:-}" ] && [ -z "${TEST_ADMIN_DSN:-}" ]; then
    STAND_URL="$(admin_url_from_stand || true)"
    if [ -n "$STAND_URL" ]; then
        export ADMIN_DATABASE_URL="$STAND_URL"
    fi
fi
if [ -z "${TEST_ADMIN_DSN:-}" ] && [ -n "${ADMIN_DATABASE_URL:-}" ]; then
    export TEST_ADMIN_DSN="$ADMIN_DATABASE_URL"
fi

# Проверки обязаны идти закреплёнными версиями. Если инструмент берётся не из
# окружения проекта, молча продолжать нельзя: именно так расхождение версий
# дважды давало ошибку, которой не было видно при разработке
case "$1" in
    python|python3|pytest|ruff|mypy|bandit|coverage|alembic|uvicorn)
        RESOLVED="$(command -v "$1" || true)"
        case "$RESOLVED" in
            "$VENV/bin/"*) : ;;
            "")  die "Команды $1 нет в окружении $VENV. Выполните: make setup" ;;
            *)   die "Команда $1 взялась не из окружения проекта: $RESOLVED
    Проверки обязаны идти закреплёнными версиями из requirements-dev.txt.
    Выполните: make setup" ;;
        esac
        ;;
esac

exec "$@"
