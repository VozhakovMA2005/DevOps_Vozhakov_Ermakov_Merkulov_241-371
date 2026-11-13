#!/usr/bin/env bash
# Конвейер проверок целиком, локально — ЛР5, пункты 4, 5, 7, 10.
#
# Запуск: make ci. Стадии и команды те же, что выполняет сервер CI: сервер
# вызывает те же цели make, по одной на стадию. Поэтому «у меня проходит, а
# на сервере нет» означает разницу окружения, а не разницу проверок.
#
# Порядок стадий — как в ТЗ 7.1 и в .github/workflows/ci.yml. Первая
# упавшая стадия останавливает конвейер: дальше не идёт ни сборка, ни
# публикация.
#
# После успешного прохода в reports/ci-passed записывается SHA коммита: по
# этой отметке make push разрешает публикацию образа. Отметка удаляется в
# начале каждого прохода, поэтому упавший конвейер публикацию запрещает.
#
# Сводка — reports/ci-summary.md, отчёты стадий — в reports/.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MAKE_CMD="${MAKE:-make}"
REPORTS="$ROOT/reports"
SUMMARY="$REPORTS/ci-summary.md"
MARKER="$REPORTS/ci-passed"

mkdir -p "$REPORTS" && chmod a+rwx "$REPORTS"
rm -f "$MARKER"

SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
MODE="$("$MAKE_CMD" --no-print-directory -s mode 2>/dev/null || echo "?")"

# Стадия: «название|цели make через пробел». Названия и порядок — как в
# ТЗ 7.1 (lint → types → sast → test → test-int → migrate-check →
# schema-check → secrets-scan → deps-check) и в .github/workflows/ci.yml,
# затем защита проверок, резервное копирование, сборка и анализ образа
STAGES=(
    "lint — стиль|quality"
    "types — типы|types"
    "sast — анализ кода на безопасность|sast"
    "test — модульные тесты|test-unit"
    "test-int — интеграционные тесты на PostgreSQL, покрытие|test-int"
    "migrate-check — обратимость миграций|migrate-check"
    "schema-check — схема совпадает с моделями|schema-check"
    "secrets-scan — секреты в дереве и коммитах ветки|secrets-scan"
    "deps-check — уязвимости зависимостей|deps-check"
    "guard — защита проверок и критических файлов|waivers guard"
    "backup — резервное копирование и восстановление|restore-drill"
    "build — сборка образа|build-app"
    "container-check — структура образа и окружения|container-check"
    "image-scan — уязвимости образа|image-scan"
)

{
    echo "# Конвейер проверок"
    echo
    echo "Коммит: \`$SHA\`  "
    echo "Способ запуска: $MODE  "
    echo "Начало: $(date '+%Y-%m-%d %H:%M:%S')"
    echo
    echo "| № | Стадия | Цели make | Время, с | Итог |"
    echo "|---|---|---|---|---|"
} > "$SUMMARY"

number=0
failed=""
for stage in "${STAGES[@]}"; do
    number=$((number + 1))
    title="${stage%%|*}"
    targets="${stage#*|}"
    printf '\n\033[1;36m==> Стадия %d из %d. %s\033[0m  (make %s)\n' \
        "$number" "${#STAGES[@]}" "$title" "$targets"
    started=$SECONDS
    # shellcheck disable=SC2086  # цели make — отдельные слова
    "$MAKE_CMD" --no-print-directory $targets
    code=$?
    spent=$((SECONDS - started))
    if [ "$code" -eq 0 ]; then
        echo "| $number | $title | \`$targets\` | $spent | пройдена |" >> "$SUMMARY"
    else
        echo "| $number | $title | \`$targets\` | $spent | **СБОЙ** |" >> "$SUMMARY"
        failed="$title"
        break
    fi
done

echo >> "$SUMMARY"
if [ -n "$failed" ]; then
    {
        echo "**Конвейер остановлен на стадии «$failed».** Следующие стадии не"
        echo "выполнялись, отметка об успешной проверке не записана: публикация"
        echo "образа (\`make push\`) запрещена."
    } >> "$SUMMARY"
    printf '\n\033[31mКонвейер остановлен на стадии «%s».\033[0m\n' "$failed"
    echo "Публикация образа запрещена: отметки reports/ci-passed нет."
    echo "Сводка: reports/ci-summary.md"
    exit 1
fi

echo "$SHA" > "$MARKER"
{
    echo "Все стадии пройдены. Отметка \`reports/ci-passed\` записана для коммита"
    echo "\`$SHA\`: публикация образа этого коммита разрешена."
} >> "$SUMMARY"
printf '\n\033[32mВсе стадии пройдены\033[0m — коммит %s\n' "$SHA"
echo "Сводка: reports/ci-summary.md, отчёты стадий — reports/"
