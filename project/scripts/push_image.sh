#!/usr/bin/env bash
# Публикация образа приложения в реестр — ЛР5, пункты 2, 9, 10.
#
#   make push REGISTRY=localhost:5000          локальный реестр (make registry-up)
#   make push REGISTRY=ghcr.io/<владелец>      реестр GitHub, после docker login
#
# Публикуется ТОЛЬКО образ, прошедший конвейер. Условия, все обязательны:
#
#   1. рабочее дерево чистое — образ соответствует коммиту, а не правкам
#      поверх него;
#   2. отметка reports/ci-passed записана make ci для этого же коммита —
#      все стадии пройдены; упавший конвейер отметку не оставляет;
#   3. образ собран из этого коммита — метка org.opencontainers.image.revision
#      совпадает с SHA.
#
# Теги: sha-<полный SHA коммита> всегда; <версия> — только если на коммите стоит
# аннотированный тег выпуска vX.Y.Z. Тег latest не ставится никогда (ТЗ 7.2).
#
# Учётные данные реестра сюда не передаются: вход выполняется заранее
# (docker login), на сервере CI — из защищённых переменных.

. "$(dirname "$0")/lib.sh"
cd "$ROOT"

APP_IMAGE="${APP_IMAGE:-audfond:0.4.0}"
IMAGE_NAME="${IMAGE_NAME:-audfond}"
REGISTRY="${REGISTRY:-}"
MARKER="reports/ci-passed"

[ -n "$REGISTRY" ] || die "Укажите реестр: make push REGISTRY=localhost:5000 (или ghcr.io/<владелец>)"
case "$REGISTRY" in
    *://*) die "REGISTRY указывается без схемы: localhost:5000, а не http://localhost:5000" ;;
esac
require_command git "Публикация привязана к коммиту: нужна рабочая копия git"
require_command docker
REPO="${REGISTRY%/}/$IMAGE_NAME"

step "Публикация $APP_IMAGE в $REPO"

SHA="$(git rev-parse HEAD 2>/dev/null)" || die "$ROOT — не рабочая копия git"

dirty="$(git status --porcelain -- . | grep -v '^?? reports/' || true)"
if [ -n "$dirty" ]; then
    printf '%s\n' "$dirty" | head -10 >&2
    die "Рабочее дерево не чистое: образ не соответствовал бы коммиту $SHA. Закоммитьте или уберите правки"
fi
ok "рабочее дерево чистое, коммит $SHA"

[ -f "$MARKER" ] || die "Нет отметки $MARKER: конвейер не пройден. Публикация запрещена — сначала make ci"
passed="$(head -1 "$MARKER")"
[ "$passed" = "$SHA" ] || die "Отметка $MARKER — для коммита $passed, а не $SHA. Публикация запрещена — make ci для текущего коммита"
ok "конвейер пройден для этого коммита ($MARKER)"

docker image inspect "$APP_IMAGE" >/dev/null 2>&1 || die "Нет образа $APP_IMAGE: make build"
revision="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$APP_IMAGE")"
case "$revision" in
    ""|unknown) die "У образа $APP_IMAGE нет метки коммита: соберите его из рабочей копии git (make build)" ;;
esac
if [ "${#revision}" -lt 7 ] || [ "${SHA#"$revision"}" = "$SHA" ]; then
    die "Образ $APP_IMAGE собран из коммита $revision, а не из $SHA: make build"
fi
ok "образ собран из этого коммита (метка revision: $revision)"

TAGS=("sha-$SHA")
release="$(git describe --exact-match --tags --match 'v[0-9]*.[0-9]*.[0-9]*' HEAD 2>/dev/null || true)"
if [ -n "$release" ]; then
    TAGS+=("${release#v}")
    ok "на коммите тег выпуска $release — образ получит и тег версии ${release#v}"
fi

for tag in "${TAGS[@]}"; do
    docker tag "$APP_IMAGE" "$REPO:$tag"
    info "docker push $REPO:$tag"
    docker push --quiet "$REPO:$tag" >/dev/null || die "Реестр не принял $REPO:$tag. Для ghcr.io нужен docker login; для локального — make registry-up"
    ok "опубликован $REPO:$tag"
done

digest="$(docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$APP_IMAGE" | grep "^$REPO@" | head -1 || true)"
[ -z "$digest" ] || info "неизменяемая ссылка на образ: $digest"
