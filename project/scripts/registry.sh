#!/usr/bin/env bash
# Локальный реестр образов — ЛР5, пункт 2 («в т.ч. локальный docker hub»).
#
#   make registry-up      запустить реестр на 127.0.0.1:5000
#   make registry-ls      что в нём лежит: образы и теги
#   make registry-down    остановить (данные остаются)
#
# Реестр слушает только 127.0.0.1: с других машин он недоступен, и Docker
# разрешает работать с ним по http без настройки insecure-registries.
# Работает не от root, без возможностей ядра, файловая система только для
# чтения; образы хранятся в каталоге пользователя и переживают перезапуск.

. "$(dirname "$0")/lib.sh"

REGISTRY_IMAGE="registry:3.0.0"
NAME="audfond-registry"
PORT="${REGISTRY_PORT:-5000}"
DATA="${REGISTRY_DIR:-$HOME/.local/share/audfond-registry}"
URL="http://127.0.0.1:$PORT"

require_command docker
require_command curl

running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; }

case "${1:-}" in
    up)
        if running; then
            ok "реестр уже работает: $URL"
            exit 0
        fi
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        mkdir -p "$DATA"
        docker run -d --name "$NAME" \
            --restart unless-stopped \
            --user "$(id -u):$(id -g)" \
            --cap-drop ALL --security-opt no-new-privileges:true \
            --read-only --tmpfs /tmp:size=16m \
            --memory 128m --cpus 0.25 --pids-limit 64 \
            -p "127.0.0.1:$PORT:5000" \
            -v "$DATA:/var/lib/registry" \
            "$REGISTRY_IMAGE" >/dev/null \
            || die "Реестр не запустился. Образ $REGISTRY_IMAGE загружается с Docker Hub: docker pull $REGISTRY_IMAGE"
        for _ in $(seq 1 20); do
            if curl -fsS -o /dev/null "$URL/v2/"; then
                ok "реестр работает: $URL, данные — $DATA"
                info "публикация: make push REGISTRY=localhost:$PORT"
                exit 0
            fi
            sleep 1
        done
        docker logs --tail 20 "$NAME" >&2 || true
        die "Реестр не ответил на $URL/v2/ за 20 секунд"
        ;;
    down)
        docker rm -f "$NAME" >/dev/null 2>&1 && ok "реестр остановлен, данные остались в $DATA" \
            || ok "реестр не был запущен"
        ;;
    ls)
        running || die "Реестр не запущен: make registry-up"
        repos="$(curl -fsS "$URL/v2/_catalog" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin).get("repositories") or []))')"
        [ -n "$repos" ] || { info "реестр пуст"; exit 0; }
        for repo in $repos; do
            echo "$repo:"
            curl -fsS "$URL/v2/$repo/tags/list" \
                | python3 -c 'import json,sys; [print("   ", t) for t in sorted(json.load(sys.stdin).get("tags") or [])]'
        done
        ;;
    *)
        die "Использование: bash scripts/registry.sh up | ls | down"
        ;;
esac
