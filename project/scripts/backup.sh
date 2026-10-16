#!/usr/bin/env bash
# Резервная копия базы — пункт 11 задания, ТЗ 4.2.
#
# Формат pg_dump -Fc (сжатый, с оглавлением): из него можно восстановить и
# базу целиком, и отдельную таблицу, и посмотреть состав копии не разворачивая.
#
#   bash scripts/backup.sh                    копия в backups/
#   bash scripts/backup.sh --keep 5           оставить пять последних
#   DATABASE_URL=... bash scripts/backup.sh   другая база
#
# Копия, которую ни разу не разворачивали, копией не считается: проверяется
# она сценарием restore_drill.sh.

. "$(dirname "$0")/lib.sh"

KEEP=10
while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP="${2:?укажите число}"; shift 2 ;;
        *) die "Неизвестный ключ: $1" ;;
    esac
done

require_command pg_dump "Поставьте postgresql-client."
load_env
parse_database_url
require_database

BACKUP_DIR="$ROOT/backups"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/audfond-$PGDATABASE-$STAMP.dump"

step "Копия базы $PGDATABASE"
info "сервер $PGHOST:$PGPORT, роль $PGUSER"
pg_dump --format=custom --compress=6 --file="$FILE"

# Проверяем, что копия читается: битый файл обнаруживается сейчас, а не в день,
# когда он понадобится
if ! pg_restore --list "$FILE" >/dev/null 2>&1; then
    rm -f "$FILE"
    die "Копия не читается, файл удалён. Проверьте версию pg_dump и права роли."
fi

SIZE="$(du -h "$FILE" | cut -f1)"
OBJECTS="$(pg_restore --list "$FILE" | grep -c '^[0-9]' || true)"
ok "создана $FILE ($SIZE, объектов в оглавлении: $OBJECTS)"

step "Старые копии"
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/audfond-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "${#OLD[@]}" -eq 0 ]; then
    info "удалять нечего, храним последние $KEEP"
else
    for old in "${OLD[@]}"; do
        rm -f "$old"
        info "удалена $(basename "$old")"
    done
    ok "оставлено последних копий: $KEEP"
fi
