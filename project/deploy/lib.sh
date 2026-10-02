#!/usr/bin/env bash
# Общее для скриптов развёртывания: вывод, проверки, безопасные правки файлов.
# Подключается строкой: . "$(dirname "$0")/lib.sh"

set -euo pipefail

#: Сеть стенда. Меняется здесь в одном месте.
NET_PREFIX="${NET_PREFIX:-192.168.56}"
APP_IP="${APP_IP:-${NET_PREFIX}.10}"
DB_IP="${DB_IP:-${NET_PREFIX}.11}"
LAN="${LAN:-${NET_PREFIX}.0/24}"
#: Сеть NAT VirtualBox: через неё идёт первое подключение по пробросу порта,
#: пока постоянные адреса стенда ещё не настроены
NAT_NET="${NAT_NET:-10.0.2.0/24}"

APP_HOST="${APP_HOST:-audfond-app}"
DB_HOST="${DB_HOST:-audfond-db}"

#: Системные учётные записи
ADMIN_USER="${ADMIN_USER:-deployer}"   # администрирование, вход по ключу, sudo
APP_USER="${APP_USER:-audfond}"        # запуск приложения, без оболочки

#: Каталоги
APP_DIR="${APP_DIR:-/opt/audfond}"
CONF_DIR="${CONF_DIR:-/etc/audfond}"

step()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    \033[32mОК\033[0m  %s\n' "$*"; }
warn()  { printf '    \033[33m!\033[0m   %s\n' "$*"; }
die()   { printf '\n\033[31mОШИБКА:\033[0m %s\n' "$*" >&2; exit 1; }

need_root() {
    [ "$(id -u)" -eq 0 ] || die "Запускать от root: sudo $0"
}

#: Идемпотентная правка «ключ значение» в конфигурационном файле.
#: Если строка есть — заменяется, нет — дописывается. Повторный запуск
#: скрипта не плодит дубликаты.
set_option() {
    local file="$1" key="$2" value="$3" sep="${4:- }"
    [ -f "$file" ] || die "Нет файла $file"
    if grep -qE "^[#[:space:]]*${key}${sep}" "$file"; then
        sed -i -E "s|^[#[:space:]]*${key}${sep}.*|${key}${sep}${value}|" "$file"
    else
        printf '%s%s%s\n' "$key" "$sep" "$value" >> "$file"
    fi
}

#: Резервная копия файла перед первой правкой — чтобы было куда вернуться
backup_once() {
    local file="$1"
    [ -f "$file" ] || return 0
    [ -f "${file}.audfond-orig" ] || cp -a "$file" "${file}.audfond-orig"
}

require_file() {
    [ -f "$1" ] || die "Нет файла $1 — $2"
}
