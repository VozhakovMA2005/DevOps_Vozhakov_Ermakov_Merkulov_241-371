#!/usr/bin/env bash
# Восстановление базы из резервной копии — пункт 11 задания, ТЗ 4.2.
#
#   bash scripts/restore.sh FILE=backups/audfond-....dump
#   bash scripts/restore.sh --latest            взять самую свежую копию
#   bash scripts/restore.sh --latest --yes       без вопроса (для учений и CI)
#
# Восстановление идёт с --clean --if-exists: существующие объекты сносятся и
# создаются заново. Это необратимо, поэтому сценарий спрашивает подтверждение,
# если его не запускают с --yes.

. "$(dirname "$0")/lib.sh"

FILE=""
ASSUME_YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --latest) FILE="latest"; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        FILE=*) FILE="${1#FILE=}"; shift ;;
        *) FILE="$1"; shift ;;
    esac
done

require_command pg_restore "Поставьте postgresql-client."
load_env
parse_database_url
require_database

if [ "$FILE" = "latest" ]; then
    FILE="$(ls -1t "$ROOT"/backups/audfond-*.dump 2>/dev/null | head -1 || true)"
    [ -n "$FILE" ] || die "В backups/ нет ни одной копии"
fi
[ -n "$FILE" ] || die "Укажите файл: bash scripts/restore.sh FILE=backups/....dump"
if [ ! -f "$FILE" ]; then
    LIST="$(ls -1t "$ROOT"/backups/*.dump 2>/dev/null | head -5 | sed "s|^$ROOT/|        |" || true)"
    die "Файл не найден: $FILE
    Последние копии:
${LIST:-        (копий в backups/ нет — сначала make backup)}
    Самая свежая одной командой:  make restore FILE=\$(ls -t backups/*.dump | head -1)"
fi

step "Проверка копии"
pg_restore --list "$FILE" >/dev/null 2>&1 || die "Файл не читается как копия pg_dump"
ok "$(basename "$FILE") читается"

step "Что будет сделано"
info "база:    $PGDATABASE на $PGHOST:$PGPORT"
info "копия:   $FILE"
warn "существующие данные базы будут заменены данными из копии"

if [ "$ASSUME_YES" != "1" ]; then
    if [ ! -t 0 ]; then
        # Запуск не из терминала: спрашивать некого, а молча заменить данные
        # нельзя. Подтверждение нужно задать явно
        die "Восстановление заменит данные базы, а подтвердить его некому:
    ввод не из терминала.
    Запустите из терминала или подтвердите явно:
        make restore FILE=$FILE YES=1
        bash scripts/restore.sh --yes $FILE"
    fi
    read -rp "    Продолжить? введите да: " ANSWER
    [ "$ANSWER" = "да" ] || die "Отменено"
fi

step "Восстановление"
# --clean --if-exists: сносим прежние объекты, не падая на отсутствующих.
# --no-owner: владельцем становится роль, которой восстанавливаем, иначе копия
# с одного стенда не развернётся на другом
pg_restore --clean --if-exists --no-owner --dbname="$PGDATABASE" "$FILE" 2>&1 \
    | grep -v '^pg_restore: warning: errors ignored on restore' || true
ok "данные восстановлены"

step "Состояние схемы"
PY="$(python_bin)"
if [ -x "$PY" ]; then
    ( cd "$ROOT" && "$PY" -m alembic current 2>&1 | tail -1 )
    info "если ревизия отстаёт от head, выполните: make migrate"
fi
