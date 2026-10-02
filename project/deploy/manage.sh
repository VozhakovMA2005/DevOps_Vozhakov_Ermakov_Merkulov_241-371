#!/usr/bin/env bash
# Служебные команды приложения — запуск в том же окружении, что у службы.
#
# Зачем отдельный скрипт. Настройки лежат в /etc/audfond/audfond.env, и
# systemd подставляет их сам (EnvironmentFile). При запуске руками этого
# никто не делает, поэтому python не видит DATABASE_URL и отказывается
# работать. Скрипт читает тот же файл и запускает команду от имени
# служебного пользователя.
#
# Запуск (на машине audfond-app):
#   sudo bash deploy/manage.sh create-admin     первый администратор
#   sudo bash deploy/manage.sh check-config     видит ли приложение настройки
#
# Пароль спрашивается с клавиатуры и не появляется ни в истории оболочки,
# ни в списке процессов.

. "$(dirname "$0")/lib.sh"

need_root
require_file "$CONF_DIR/audfond.env" "сначала выполните 03-app-server.sh"
require_file "$APP_DIR/.venv/bin/python" "сначала выполните deploy.sh"

PY="$APP_DIR/.venv/bin/python"

# Загружаем настройки службы в своё окружение. set -a помечает всё
# прочитанное на экспорт, иначе дочерний процесс их не увидит.
set -a
# shellcheck disable=SC1091
. "$CONF_DIR/audfond.env"
set +a

# Запускаемся из каталога приложения: служебный пользователь не имеет доступа
# к домашним каталогам, а импорт пакета app ищется от текущего каталога.
cd "$APP_DIR"
export PYTHONPATH="$APP_DIR"

# runuser входит в util-linux и есть в Debian всегда; окружение он сохраняет.
as_app_user() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$APP_USER" -- "$@"
    else
        sudo -u "$APP_USER" -E "$@"
    fi
}

cmd_create_admin() {
    step "Первый администратор системы"
    info "роль SYS_ADMIN, пункт ТЗ 4.1.1"

    read -rp "    Логин [admin]: " ADMIN_USERNAME
    ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
    read -rp "    ФИО [Администратор системы]: " ADMIN_FULL_NAME
    ADMIN_FULL_NAME="${ADMIN_FULL_NAME:-Администратор системы}"
    read -rsp "    Пароль (не короче 8 символов): " ADMIN_PASSWORD; echo
    read -rsp "    Пароль повторно: " ADMIN_PASSWORD_AGAIN; echo

    [ "$ADMIN_PASSWORD" = "$ADMIN_PASSWORD_AGAIN" ] || die "Пароли не совпали"
    [ -n "$ADMIN_PASSWORD" ] || die "Пароль пустой"

    export ADMIN_USERNAME ADMIN_FULL_NAME ADMIN_PASSWORD
    as_app_user "$PY" "$APP_DIR/scripts/create_admin.py"
}

cmd_check_config() {
    step "Проверка настроек приложения"
    as_app_user "$PY" -c '
from app.config import load_config
c = load_config()
print(f"    окружение:  {c.app_env}")
print(f"    база:       {c.database_url.rsplit(chr(64), 1)[-1]}")
print(f"    ключ JWT:   задан, {len(c.jwt_secret)} символов")
' || die "приложение не принимает настройки из $CONF_DIR/audfond.env"
    ok "настройки читаются"
}

case "${1:-}" in
    create-admin)  cmd_create_admin ;;
    check-config)  cmd_check_config ;;
    *)
        echo "Использование: sudo bash $0 {create-admin|check-config}" >&2
        exit 2
        ;;
esac
