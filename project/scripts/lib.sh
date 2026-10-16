#!/usr/bin/env bash
# Общее для сценариев проекта: вывод и разбор адреса базы.
#
# Подключается строкой: . "$(dirname "$0")/lib.sh"

set -euo pipefail

step()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    \033[32mОК\033[0m  %s\n' "$*"; }
warn()  { printf '    \033[33m!\033[0m   %s\n' "$*"; }
die()   { printf '\n\033[31mОШИБКА:\033[0m %s\n' "$*" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

# Настройки берутся из окружения, а если его нет — из .env (ТЗ 4.6: только
# переменные окружения, в репозитории значений нет)
load_env() {
    if [ -z "${DATABASE_URL:-}" ] && [ -f "$ROOT/.env" ]; then
        set -a
        # shellcheck disable=SC1091
        . "$ROOT/.env"
        set +a
    fi
    [ -n "${DATABASE_URL:-}" ] || die "Не задана DATABASE_URL (окружение или .env)"
}

# DATABASE_URL -> переменные PG*. Пароль уходит в PGPASSWORD, а не в командную
# строку: аргументы видны в списке процессов
parse_database_url() {
    local url="${1:-$DATABASE_URL}"
    # postgresql+psycopg://user:pass@host:port/dbname?params
    local stripped="${url#*://}"
    stripped="${stripped%%\?*}"

    local credentials="${stripped%%@*}"
    local location="${stripped##*@}"

    export PGUSER="${credentials%%:*}"
    if [[ "$credentials" == *:* ]]; then
        PGPASSWORD="${credentials#*:}"
        export PGPASSWORD
    fi

    local hostport="${location%%/*}"
    export PGDATABASE="${location##*/}"
    export PGHOST="${hostport%%:*}"
    if [[ "$hostport" == *:* ]]; then
        export PGPORT="${hostport##*:}"
    else
        export PGPORT=5432
    fi
}

# База из DATABASE_URL должна отвечать до начала работы: иначе pg_dump и
# pg_restore выдают длинную ошибку libpq без подсказки, что поправить
require_database() {
    pg_isready -q -t 3 2>/dev/null && return 0
    case "$PGHOST" in
        localhost|127.0.0.1|::1)
            die "База $PGHOST:$PGPORT не отвечает: DATABASE_URL в .env указывает на эту же
    машину, а на стенде база живёт на сервере audfond-db. Впишите в .env проекта
    (адрес владельца схемы, пароль — OWNER_PASSWORD из /etc/audfond/db-passwords
    на сервере базы):
        DATABASE_URL=postgresql+psycopg://af_owner:ПАРОЛЬ_МИГРАЦИЙ@192.168.56.11:5432/audfond" ;;
    esac
    die "База $PGHOST:$PGPORT не отвечает. Проверьте, что сервер базы запущен и порт
    5432 открыт для этой машины: pg_isready -h $PGHOST -p $PGPORT"
}

# Роль, которой можно создавать базы. Роль приложения этого НЕ может и не
# должна: подраздел 4.4 ТЗ разделяет владельца схемы и приложение. Поэтому
# учениям нужен отдельный адрес, как и набору тестов
# Адрес роли учений со стенда: роль af_drill заведена сценарием
# 02-db-server.sh, её пароль лежит в файле паролей, а адрес сервера базы
# берётся из настроек приложения. Печатает адрес или ничего.
admin_url_from_stand() {
    [ -r /etc/audfond/db-passwords ] || return 1
    local drill hostport
    drill="$(grep '^DRILL_PASSWORD=' /etc/audfond/db-passwords 2>/dev/null | cut -d= -f2-)"
    [ -n "$drill" ] || return 1

    local url="${DATABASE_URL:-}"
    if [ -z "$url" ] && [ -r /etc/audfond/audfond.env ]; then
        url="$(grep -E '^DATABASE_URL=' /etc/audfond/audfond.env | cut -d= -f2-)"
    fi
    [ -n "$url" ] || return 1

    hostport="$(printf '%s' "$url" | sed -E 's|.*@([^/?]+)/.*|\1|')"
    printf 'postgresql://af_drill:%s@%s/postgres' "$drill" "$hostport"
}

load_admin_env() {
    ADMIN_URL="${ADMIN_DATABASE_URL:-${TEST_ADMIN_DSN:-}}"

    # На стенде адрес задавать руками не нужно: он выводится из роли учений
    if [ -z "$ADMIN_URL" ]; then
        ADMIN_URL="$(admin_url_from_stand || true)"
        [ -n "$ADMIN_URL" ] && info "адрес учений взят из роли af_drill"
    fi

    if [ -z "$ADMIN_URL" ]; then
        die "Нужна роль с правом создавать базы: учения поднимают одноразовые
    базы, а роль приложения этого не может и не должна (ТЗ 4.4).

    На стенде роль af_drill заводится сценарием deploy/02-db-server.sh.
    Если стенд собран до этапа 3, запустите его повторно на сервере базы —
    пароли он возьмёт из своего файла паролей, задавать их не нужно:
        cd ~/deploy && sudo bash 02-db-server.sh

    Затем на машине приложения впишите адрес в .env проекта:
        ADMIN_DATABASE_URL=postgresql://af_drill:ПАРОЛЬ_УЧЕНИЙ@192.168.56.11:5432/postgres
    Пароль — строка DRILL_PASSWORD в /etc/audfond/db-passwords на сервере базы:
        sudo grep DRILL_PASSWORD /etc/audfond/db-passwords

    Вручную:
        ADMIN_DATABASE_URL=postgresql://postgres@localhost:5432/postgres \\
          make migrate-drill"
    fi
    parse_database_url "$ADMIN_URL"
}

# Адрес той же базы, но с другим именем: нужен учениям по миграциям
database_url_for() {
    local name="$1"
    printf 'postgresql+psycopg://%s:%s@%s:%s/%s' \
        "$PGUSER" "${PGPASSWORD:-}" "$PGHOST" "$PGPORT" "$name"
}

python_bin() {
    if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ]; then
        printf '%s' "$PYTHON"   # для прогона на другом окружении
    elif [ -x "$VENV/bin/python" ]; then
        printf '%s' "$VENV/bin/python"
    else
        command -v python3
    fi
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Нужна команда $1. ${2:-}"
}

wait_for_database() {
    local attempts="${1:-20}"
    for _ in $(seq 1 "$attempts"); do
        if pg_isready -q 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}
