#!/usr/bin/env bash
# Проверка образа по требованиям ТЗ 4.5 и 7.2:
#   процесс не от root, тег не latest, есть healthcheck, порт базы не наружу.
set -uo pipefail

IMAGE="${IMAGE:-audfond:0.1.0}"
FAILED=0

check() {
    if [ "$2" = "0" ]; then
        printf '  ОК    %s\n' "$1"
    else
        printf '  СБОЙ  %s\n' "$1"
        FAILED=1
    fi
}

echo "Проверяю образ $IMAGE"

docker image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "Образ $IMAGE не собран. Выполните make up" >&2
    exit 2
}

USER_IN_IMAGE=$(docker image inspect -f '{{.Config.User}}' "$IMAGE")
[ -n "$USER_IN_IMAGE" ] && [ "$USER_IN_IMAGE" != "root" ] && [ "$USER_IN_IMAGE" != "0" ]
check "процесс работает не от root (пользователь: ${USER_IN_IMAGE:-root})" $?

! grep -qE '^FROM .*:latest' docker/Dockerfile
check "теги базовых образов закреплены, latest не используется" $?

[ "$(docker image inspect -f '{{if .Config.Healthcheck}}yes{{end}}' "$IMAGE")" = "yes" ]
check "в образе объявлен healthcheck" $?

! grep -qE '^\s+- "?\$\{POSTGRES_PORT_EXPOSED' docker-compose.yml
check "порт СУБД не публикуется наружу" $?

! docker image inspect -f '{{json .Config.Env}}' "$IMAGE" | grep -qiE 'password|secret|token'
check "в переменных образа нет секретов" $?

exit $FAILED
