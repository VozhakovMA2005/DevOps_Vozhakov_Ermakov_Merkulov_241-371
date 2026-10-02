#!/usr/bin/env bash
# Проверка стенда по пунктам защиты лабораторной работы №2.
# Запускать на сервере приложения ОТ ROOT: sudo bash check.sh
#
# Почему от root: sshd -T и ufw status читают настройки, закрытые для
# обычного пользователя. Без sudo эти три проверки покажут ложный сбой.
#
# Скрипт не чинит, а проверяет и называет команду, которой проверял, —
# чтобы на защите можно было показать то же самое руками.

. "$(dirname "$0")/lib.sh"

need_root
set +e   # проверки идут до конца, даже если какая-то не прошла

PASSED=0
FAILED=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '  \033[32mОК  \033[0m %s\n' "$name"
        PASSED=$((PASSED + 1))
    else
        printf '  \033[31mСБОЙ\033[0m %s\n' "$name"
        FAILED=$((FAILED + 1))
    fi
}

not() { ! "$@"; }

step "Служба"
check "служба audfond включена в автозапуск"  systemctl is-enabled --quiet audfond
check "служба audfond работает"               systemctl is-active --quiet audfond
check "приложение работает НЕ от root"        bash -c '[ "$(systemctl show -p User --value audfond)" != "root" ]'
check "настроен перезапуск после сбоя"        bash -c '[ "$(systemctl show -p Restart --value audfond)" = "on-failure" ]'

step "Приложение"
check "/healthz отвечает"   curl -fsS http://127.0.0.1:8000/healthz
check "/readyz отвечает"    curl -fsS http://127.0.0.1:8000/readyz
check "/version отвечает"   curl -fsS http://127.0.0.1:8000/version

step "Сеть и порты"
check "порт 8000 слушается"      bash -c "ss -ltn | grep -q ':8000'"
check "база отвечает с сервера приложения" bash -c "timeout 3 bash -c '</dev/tcp/$DB_IP/5432'"
check "лишних портов наружу нет" bash -c "! ss -ltn | grep -qE ':(3306|6379|11211|27017)\b'"

step "Доступ"
check "удалённый вход под root запрещён"  bash -c "sshd -T 2>/dev/null | grep -q '^permitrootlogin no'"
check "вход по паролю запрещён"           bash -c "sshd -T 2>/dev/null | grep -q '^passwordauthentication no'"
check "межсетевой экран включён"          bash -c "ufw status | head -1 | grep -q 'active'"

step "Вход в приложение"
# Браузер не сохраняет cookie с флагом Secure, пришедшую по http. Если
# COOKIE_SECURE=true, а TLS перед приложением нет, вход внешне не работает:
# пароль принимается, но страница возвращает на форму.
check "cookie входа согласована с протоколом" \
    bash -c '! grep -qiE "^COOKIE_SECURE=[[:space:]]*(1|true|yes|on)" /etc/audfond/audfond.env'
check "форма входа отдаётся"                  bash -c "curl -fsS http://127.0.0.1:8000/login | grep -q 'password'"
check "неверный пароль отклоняется"           bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"нет-такого\",\"password\":\"неверный-пароль\"}')\" = 401 ]"

step "Файлы и настройки"
check "настройки лежат вне кода"          test -f "$CONF_DIR/audfond.env"
check "настройки не читает посторонний"   bash -c "[ \"\$(stat -c %a $CONF_DIR/audfond.env)\" = '640' ]"
check "в каталоге кода нет файла .env"    not test -f "$APP_DIR/.env"
check "каталог кода закрыт от посторонних" bash -c "[ \"\$(stat -c %a $APP_DIR)\" = '750' ]"

step "Итог"
printf '  пройдено: %s, сбоев: %s\n' "$PASSED" "$FAILED"
if [ "$FAILED" -gt 0 ]; then
    printf '\n  Что смотреть при сбое:\n'
    printf '    systemctl status audfond\n'
    printf '    journalctl -u audfond -n 50 --no-pager\n'
    printf '    sudo ufw status numbered\n'
    exit 1
fi
printf '\n  Стенд соответствует требованиям работы.\n'
