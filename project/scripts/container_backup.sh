#!/usr/bin/env bash
# Резервная копия базы в контейнерной среде — ЛР4, пункт 10.
#
# pg_dump запускается ВНУТРИ контейнера базы: его версия всегда совпадает с
# версией сервера, а порт базы наружу публиковать не нужно. Копия выходит
# через stdout и ложится на машину в backups/ — вне контейнеров и томов,
# поэтому переживает и удаление тома.
#
#   bash scripts/container_backup.sh     (make backup при LOCAL=0)

. "$(dirname "$0")/container_lib.sh"

KEEP="${KEEP:-10}"
step "Копия базы $POSTGRES_DB из контейнера db"
wait_healthy db 30 || die "Служба db не запущена или нездорова: make up"

mkdir -p "$ROOT/backups"
FILE="$ROOT/backups/audfond-docker-$(date +%Y%m%d-%H%M%S).dump"
db_exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --format=custom --compress=6 > "$FILE" || { rm -f "$FILE"; die "pg_dump не отработал"; }

# Копия должна читаться: проверяем оглавление тем же pg_restore из контейнера
OBJECTS="$(db_exec pg_restore --list < "$FILE" | grep -c '^[0-9]' || true)"
[ "${OBJECTS:-0}" -gt 0 ] || { rm -f "$FILE"; die "Копия не читается, файл удалён"; }
ok "копия: ${FILE#"$ROOT"/} ($(du -h "$FILE" | cut -f1), объектов: $OBJECTS)"

mapfile -t OLD < <(ls -1t "$ROOT"/backups/audfond-docker-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))")
[ "${#OLD[@]}" -eq 0 ] || { rm -f "${OLD[@]}"; info "удалено старых копий: ${#OLD[@]}"; }
