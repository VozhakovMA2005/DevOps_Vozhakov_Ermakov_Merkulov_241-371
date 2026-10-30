#!/usr/bin/env bash
# Восстановление базы в контейнерной среде — ЛР4, пункт 10.
#
#   bash scripts/container_restore.sh FILE=backups/....dump [--yes]
#
# На время восстановления экземпляры приложения останавливаются: иначе их
# открытые соединения мешают пересоздать объекты, а пользователи видят базу
# наполовину восстановленной. После — запускаются снова и проверяются.

. "$(dirname "$0")/container_lib.sh"

FILE="" ; ASSUME_YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        FILE=*) FILE="${1#FILE=}" ;;
        *) FILE="$1" ;;
    esac
    shift
done
[ -n "$FILE" ] || die "Укажите файл: make restore FILE=\$(ls -t backups/*.dump | head -1)"
[ -f "$FILE" ] || die "Файл не найден: $FILE
    Последние копии:
$(ls -1t "$ROOT"/backups/*.dump 2>/dev/null | head -5 | sed "s|^$ROOT/|        |")"

step "Восстановление базы $POSTGRES_DB из ${FILE#"$ROOT"/}"
wait_healthy db 30 || die "Служба db не запущена или нездорова: make up"
if [ "$ASSUME_YES" != "1" ]; then
    [ -t 0 ] || die "Не из терминала подтверждение задаётся явно: --yes (YES=1)"
    read -r -p "    Текущие данные будут заменены. Продолжить? [да/нет] " answer
    case "$answer" in да|Да|y|yes) ;; *) die "Отменено" ;; esac
fi

info "остановка экземпляров приложения"
compose stop app1 app2 >/dev/null 2>&1 || true

db_exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --no-owner --exit-on-error < "$FILE" \
    || die "pg_restore не отработал — приложение остановлено, база в прежнем виде не гарантируется"
ok "копия развёрнута"

info "запуск экземпляров приложения"
compose up -d app1 app2 >/dev/null 2>&1
wait_healthy app1 60 && wait_healthy app2 60 || die "Приложение не стало здоровым после восстановления"
ok "app1 и app2 здоровы, помещений в базе: $(db_sql 'SELECT count(*) FROM room')"
