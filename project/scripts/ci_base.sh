#!/usr/bin/env bash
# С чем сравнивать ветку на сервере CI — для make guard и make secrets-branch.
#
# Печатает строку BASE=<ссылка> (задача CI дописывает её в GITHUB_ENV):
#   запрос на слияние, ветка, тег — origin/main;
#   push в main — состояние main до этого push (github.event.before):
#   проверяется то, что только что влито.
#
# Переменные: EVENT_NAME, REF, BEFORE — из контекста github.
set -euo pipefail

base="origin/main"
if [ "${EVENT_NAME:-}" = "push" ] && [ "${REF:-}" = "refs/heads/main" ]; then
    if [ -n "${BEFORE:-}" ] && [ "${BEFORE//0/}" != "" ] \
        && git cat-file -e "${BEFORE}^{commit}" 2>/dev/null; then
        base="$BEFORE"
    else
        base="HEAD~1"
    fi
fi
echo "BASE=$base"
