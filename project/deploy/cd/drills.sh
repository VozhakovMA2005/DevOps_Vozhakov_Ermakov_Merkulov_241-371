#!/usr/bin/env bash
# Запускать только на выделенном staging после двух опубликованных SHA-образов.
set -euo pipefail
root=/srv/audfond-staging
controller=/opt/audfond-cd/cd.py
candidate="${1:?Укажите sha-<40 hex> другого проверенного образа для опыта с healthcheck}"
[[ "$candidate" =~ ^sha-[0-9a-f]{40}$ ]] || exit 1
python3 "$controller" check --root "$root"
tmp="$(mktemp -d "$root/drill.XXXXXXXX")"
chmod 700 "$tmp"
cp "$root/app.env" "$tmp/app.env"
cp "$root/deploy.env" "$tmp/deploy.env"
cleanup() {
  cp "$tmp/app.env" "$root/app.env"
  cp "$tmp/deploy.env" "$root/deploy.env"
  chmod 600 "$root/app.env" "$root/deploy.env"
  rm -rf -- "$tmp"
}
trap cleanup EXIT
must_fail() {
  if "$@"; then
    echo 'Ожидаемый отказ не произошел; опыт остановлен' >&2
    exit 1
  fi
}
must_fail python3 "$controller" deploy --root "$root" --tag latest
must_fail python3 "$controller" deploy --root "$root" --tag 99.99.99
sed -i 's/^JWT_SECRET=.*/JWT_SECRET=/' "$root/app.env"
must_fail python3 "$controller" deploy --root "$root" --tag "$candidate"
cp "$tmp/app.env" "$root/app.env"
sed -i 's|^IMAGE_REPOSITORY=.*|IMAGE_REPOSITORY=127.0.0.1:59999/audfond|' "$root/deploy.env"
must_fail python3 "$controller" deploy --root "$root" --tag "$candidate"
cp "$tmp/deploy.env" "$root/deploy.env"
python3 "$controller" check --root "$root"
# Candidate must differ from current, otherwise idempotent check is expected.
python3 - "$root/release-state.json" "$candidate" <<'PY'
import json
import sys
state = json.load(open(sys.argv[1], encoding='utf-8'))
assert state['current']['commit'] != sys.argv[2][4:], 'Нужен кандидат другого коммита'
PY
sed -i 's/^APP_PORT=.*/APP_PORT=8001/' "$root/app.env"
must_fail python3 "$controller" deploy --root "$root" --tag "$candidate"
cp "$tmp/app.env" "$root/app.env"
python3 "$controller" recover --root "$root"
python3 "$controller" check --root "$root"
echo 'Опыты с тегом, переменной, registry и healthcheck завершены; current проверен'
