#!/usr/bin/env bash
# Общее для сценариев контейнерного окружения (ЛР4).
#
# Подключается строкой: . "$(dirname "$0")/container_lib.sh"

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_DOCKER="$ROOT/.env.docker"
[ -f "$ENV_DOCKER" ] || die "Нет .env.docker — создайте: make docker-env"
require_command docker "Установите Docker (docs/containers.md, раздел 1)."
docker compose version >/dev/null 2>&1 || die "Нет docker compose (пакет docker-compose-plugin)."

# Значения из .env.docker нужны и самим сценариям: имя базы и роль
set -a
# shellcheck disable=SC1090
. "$ENV_DOCKER"
set +a
POSTGRES_USER="${POSTGRES_USER:-audfond}"
POSTGRES_DB="${POSTGRES_DB:-audfond}"

compose() {
    docker compose --project-directory "$ROOT" --env-file "$ENV_DOCKER" "$@"
}

# Ждать, пока служба станет здоровой (healthcheck), не дольше N секунд
wait_healthy() {
    local service="$1" seconds="${2:-60}" id status
    for _ in $(seq 1 "$seconds"); do
        id="$(compose ps -q "$service" 2>/dev/null)"
        if [ -n "$id" ]; then
            status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)"
            [ "$status" = "healthy" ] && return 0
        fi
        sleep 1
    done
    return 1
}

# Команда внутри контейнера базы. Пароль передаётся переменной окружения
# только этой команде: так вход работает при любом способе проверки
# подлинности внутри контейнера
db_exec() {
    compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" db "$@"
}

# SQL в базе контейнера от имени владельца базы
db_sql() {
    db_exec psql -v ON_ERROR_STOP=1 -qtA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"
}

# Адрес, по которому Nginx доступен с этой машины. Если порт опубликован
# только на одном адресе (HTTP_BIND=192.168.56.10), на 127.0.0.1 его нет
case "${HTTP_BIND:-0.0.0.0}" in
    0.0.0.0|"") BASE_URL="http://127.0.0.1:${HTTP_PORT:-8080}" ;;
    *)          BASE_URL="http://${HTTP_BIND}:${HTTP_PORT:-8080}" ;;
esac

# Запрос через Nginx — так, как ходит клиент
http_get() {
    curl -fsS --max-time 5 "$BASE_URL$1"
}
