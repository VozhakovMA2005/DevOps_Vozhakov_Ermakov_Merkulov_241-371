#!/usr/bin/env bash
# Учения контейнерного окружения — ЛР4, проверка на защите.
#
#   bash scripts/container_drill.sh persist      данные переживают пересоздание
#                                                контейнеров и обновление образа
#   bash scripts/container_drill.sh shutdown     корректное завершение по SIGTERM
#   bash scripts/container_drill.sh failover     балансировка, отказ узла, повтор,
#                                                ограничение частоты (доп. задание)
#   bash scripts/container_drill.sh new-volume FILE=backups/....dump
#                                                восстановление в НОВЫЙ том
#
# Учения работают с запущенным окружением (make up) и возвращают его в
# рабочее состояние. Каждый шаг печатает, что проверено; при расхождении —
# ошибка и ненулевой код возврата.

. "$(dirname "$0")/container_lib.sh"
require_command curl "Поставьте curl."

ensure_up() {
    for service in db app1 app2 nginx; do
        wait_healthy "$service" 5 || die "Окружение не запущено или нездорово ($service): make up"
    done
}

# ---------------------------------------------------------------------------
persist() {
    ensure_up
    local marker="DRILL-$(date +%H%M%S)" volume_before volume_after commit_before commit_after

    step "1. Метка в базе"
    db_sql "INSERT INTO department (code, name) VALUES ('$marker', 'Метка учений: проверка сохранности')"
    ok "записано подразделение $marker"
    volume_before="$(docker volume inspect -f '{{.CreatedAt}}' "${DB_VOLUME:-audfond_db-data}")"
    info "том ${DB_VOLUME:-audfond_db-data} создан: $volume_before"

    step "2. Пересоздание всех контейнеров"
    compose up -d --force-recreate --wait >/dev/null 2>&1
    [ "$(db_sql "SELECT count(*) FROM department WHERE code = '$marker'")" = "1" ] \
        || die "после пересоздания контейнеров метки нет — данные потеряны"
    ok "контейнеры новые, метка на месте"

    step "3. Обновление образа приложения"
    commit_before="$(http_get /version | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')"
    GIT_COMMIT="drill-$(date +%H%M%S)" compose build migrate >/dev/null 2>&1
    GIT_COMMIT="drill-$(date +%H%M%S)" compose up -d --wait >/dev/null 2>&1
    commit_after="$(http_get /version | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')"
    [ "$commit_before" != "$commit_after" ] || die "образ не обновился: коммит прежний ($commit_after)"
    ok "образ пересобран: коммит $commit_before → $commit_after"
    [ "$(db_sql "SELECT count(*) FROM department WHERE code = '$marker'")" = "1" ] \
        || die "после обновления образа метки нет — данные потеряны"
    ok "после обновления образа метка на месте"

    volume_after="$(docker volume inspect -f '{{.CreatedAt}}' "${DB_VOLUME:-audfond_db-data}")"
    [ "$volume_before" = "$volume_after" ] || die "том пересоздан: данные хранятся не на постоянном томе"
    ok "том тот же самый (создан $volume_after)"

    db_sql "DELETE FROM department WHERE code = '$marker'"
    info "метка удалена"
    step "Итог"
    ok "данные пережили пересоздание контейнеров и обновление образа (пункт 9)"
    info "образ текущего коммита восстанавливается командой make up"
}

# ---------------------------------------------------------------------------
shutdown() {
    ensure_up
    local id started elapsed code
    # Что бы ни случилось в учениях, app1 должен вернуться в строй
    trap 'compose start app1 >/dev/null 2>&1 || true' EXIT

    step "1. Остановка app1 сигналом SIGTERM (docker stop)"
    id="$(compose ps -q app1)"
    local since
    since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    started="$(date +%s%N)"
    compose stop app1 >/dev/null 2>&1
    elapsed=$(( ($(date +%s%N) - started) / 1000000 ))
    code="$(docker inspect -f '{{.State.ExitCode}}' "$id")"
    info "остановлен за ${elapsed} мс, код выхода $code"
    [ "$code" = "0" ] || die "код выхода $code: процесс убит, а не завершился сам (137 = SIGKILL)"
    ok "код 0: сервер завершился сам, а не был убит по истечении stop_grace_period"

    step "2. Что сервер сделал при остановке"
    local logs
    logs="$(docker logs --since "$since" "$id" 2>&1)"
    grep -E "Shutting down|Waiting for application shutdown|AudFond остановлен|Finished server process" \
        <<<"$logs" | sed 's/^/    /' || true
    grep -q "AudFond остановлен" <<<"$logs" \
        || die "в журнале нет записи о закрытии соединений с базой"
    ok "соединения с базой закрыты, процесс завершён"

    step "3. Сервис при этом доступен"
    http_get /healthz >/dev/null && ok "через Nginx отвечает app2"

    compose start app1 >/dev/null 2>&1
    wait_healthy app1 60 || die "app1 не запустился повторно"
    ok "app1 запущен снова и здоров"
}

# ---------------------------------------------------------------------------
instances() {
    # Кто ответил на N запросов подряд: «app-1 app-2 app-1 …»
    local n="$1" i
    for i in $(seq 1 "$n"); do
        curl -fsS --max-time 5 -o /dev/null -D - "$BASE_URL/healthz" \
            | tr -d '\r' | awk -F': ' 'tolower($1)=="x-instance"{print $2}'
    done
}

failover() {
    ensure_up
    local seen
    trap 'compose start app2 >/dev/null 2>&1 || true' EXIT

    step "1. Распределение запросов между экземплярами"
    seen="$(instances 10 | sort | uniq -c | sed 's/^ */    /')"
    printf '%s\n' "$seen"
    grep -q app-1 <<<"$seen" && grep -q app-2 <<<"$seen" \
        || die "запросы обрабатывает один экземпляр — балансировки нет"
    ok "запросы идут на оба экземпляра (заголовок X-Instance)"

    step "2. Отказ узла: app2 остановлен"
    compose stop app2 >/dev/null 2>&1
    seen="$(instances 10 | sort | uniq -c | sed 's/^ */    /')"
    printf '%s\n' "$seen"
    [ "$(instances 10 | grep -c app-1)" = "10" ] || die "при остановленном app2 запросы теряются"
    ok "10 из 10 запросов успешны: Nginx исключил app2 и повторил запрос на app1"

    step "3. Узел вернулся"
    compose start app2 >/dev/null 2>&1
    wait_healthy app2 60 || die "app2 не запустился повторно"
    sleep 11   # fail_timeout=10s: столько Nginx не пробует исключённый узел
    seen="$(instances 10 | sort | uniq -c | sed 's/^ */    /')"
    printf '%s\n' "$seen"
    grep -q app-2 <<<"$seen" || die "app2 не вернулся в распределение"
    ok "app2 снова получает запросы"

    step "4. Ограничение частоты входа"
    local codes
    codes="$(for _ in $(seq 1 15); do
        curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 -X POST \
            -H 'Content-Type: application/json' -d '{"username":"нет","password":"нет"}' \
            "$BASE_URL/api/v1/auth/login"
    done | sort | uniq -c | sed 's/^ */    /')"
    printf '%s\n' "$codes"
    grep -q " 429" <<<"$codes" || die "ограничение частоты не сработало"
    ok "после серии попыток Nginx отвечает 429, до приложения они не доходят"

    step "5. Прямого доступа к приложению нет"
    local published
    published="$(docker port "$(compose ps -q app1)"; docker port "$(compose ps -q app2)")"
    [ -z "$published" ] || die "порт приложения опубликован: $published"
    ok "у app1 и app2 нет опубликованных портов: снаружи — только Nginx ($BASE_URL)"
}

# ---------------------------------------------------------------------------
new_volume() {
    local file="" new_volume rooms_before rooms_after
    for arg in "$@"; do
        case "$arg" in FILE=*) file="${arg#FILE=}" ;; *) file="$arg" ;; esac
    done
    [ -n "$file" ] && [ -f "$file" ] || die "Укажите копию: make restore-new-volume FILE=\$(ls -t backups/*.dump | head -1)"
    new_volume="audfond_db-restored-$(date +%Y%m%d-%H%M%S)"

    step "1. Исходное состояние"
    rooms_before="$(db_exec pg_restore --data-only --table=room -f - < "$file" 2>/dev/null \
        | sed -n '/^COPY public.room /,/^\\\./p' | grep -vc -e '^COPY' -e '^\\\.' || true)"
    info "в копии ${file#"$ROOT"/} помещений: $rooms_before"
    info "сейчас база на томе: $(docker inspect -f '{{range .Mounts}}{{.Name}}{{end}}' "$(compose ps -q db)")"

    step "2. Окружение останавливается, старый том НЕ удаляется"
    compose down >/dev/null 2>&1
    ok "контейнеры удалены, том ${DB_VOLUME:-audfond_db-data} на месте"

    step "3. База на новом пустом томе $new_volume"
    export DB_VOLUME="$new_volume"
    compose up -d db >/dev/null 2>&1
    wait_healthy db 90 || die "база на новом томе не поднялась"
    [ "$(db_sql "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")" = "0" ] \
        || die "новый том не пустой"
    ok "том создан, база пустая"

    step "4. Восстановление из копии"
    db_exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error < "$file" \
        || die "pg_restore не отработал"
    rooms_after="$(db_sql 'SELECT count(*) FROM room')"
    [ "$rooms_after" = "$rooms_before" ] || die "помещений $rooms_after, а в копии $rooms_before"
    ok "данные развёрнуты: помещений $rooms_after"

    step "5. Окружение целиком поверх восстановленного тома"
    compose up -d --wait >/dev/null 2>&1 || die "окружение не поднялось"
    http_get /readyz >/dev/null 2>&1 || die "приложение не готово"
    ok "migrate, app1, app2 и nginx работают, /readyz отвечает"

    step "Итог"
    ok "база восстановлена в новый том $new_volume"
    info "окружение работает на новом томе; варианты:"
    info "  сохранить новый том:     строка DB_VOLUME=$new_volume в .env.docker"
    info "  вернуться к старому тому: make down && make up (старый том не изменён)"
}

case "${1:-}" in
    persist) persist ;;
    shutdown) shutdown ;;
    failover) failover ;;
    new-volume) shift; new_volume "$@" ;;
    *) die "Использование: $0 persist | shutdown | failover | new-volume FILE=…" ;;
esac
